"""Text2SQL 核心：组装 Prompt（schema + few-shot）→ 生成 SQL → 安全校验
→ 执行 → 出错则把错误回喂模型自动修正（自校验重试闭环，见 PRD 图 2.2）。"""
import re
from .llm import chat
from .db import run_query
from .sql_guard import ensure_safe, with_limit, UnsafeSQLError
from .schema_linking import link_schema
from .config import MAX_SQL_RETRY

# 领域提示：把懂车帝销量榜星型模型的语义/枚举喂给 LLM（schema introspection 只给类型，缺业务含义）
DOMAIN = """库为「车市镜」新能源汽车销量分析库（懂车帝榜单，全国口径，月粒度）。星型模型：
- dim_series(series_id, series_name 车系名如「小米SU7」「理想L6」, brand_id, powertrain 动力 纯电/插混/增程, guide_price_min/max 指导价万元)
- dim_brand(brand_id, brand_name 品牌名如「理想汽车」「比亚迪」)
- dim_date(date_id 自增整数, year, month, quarter, ym 形如 '2025-05') ⚠️ date_id 不是 YYYYMM 格式，按时间过滤必须 JOIN dim_date 用 year/month 字段
- fact_sales_rank(series_id, date_id, new_energy_type 能源类型[1纯电/2插混/3增程], rank 当月排名, last_rank 上期排名[NULL=新上榜], volume 销量[核心度量,单位辆])
- fact_price(series_id, date_id, guide_price_min/max, dealer_price_text 经销商报价, descender_price 降价幅度)
- fact_review(series_id, date_id, review_count 口碑数, score 口碑评分[0-5分，部分车系为NULL])
关键口径：
- 「销量」=fact_sales_rank.volume，跨月需 SUM；某月销量需 JOIN dim_date 按 year/month 过滤。
- 能源类型用 fact_sales_rank.new_energy_type 数字过滤：纯电=1、插混=2、增程=3。注意 dim_series.powertrain 存的也是 '纯电'/'插混'/'增程' 文本，但做能源类型聚合/分组时应使用 fact_sales_rank.new_energy_type。
- 车系名/品牌名模糊匹配用 LIKE '%关键词%'。当前年份：2026。
- 品牌名匹配注意：dim_brand 中存储的是简称（如「理想」而非「理想汽车」，「五菱」而非「五菱汽车」），LIKE 时用最短唯一前缀（如 '%理想%'、'%五菱%'）。
- 问「XX累计销量」时只需返回汇总数值（SELECT SUM(...) v），不需要额外输出车系/品牌名列。
- score 是口碑评分（0-5 分），**部分车系为 NULL**（无人评分）；按口碑排序/筛选时必须先 `WHERE score IS NOT NULL` 再 ORDER BY score DESC，避免 NULL 混进结果。
- 品牌名必须来自这个列表（不在列表里的品牌数据库里没有数据，问就是查不到）：
  比亚迪, 特斯拉, 理想, 蔚来, 小鹏, 零跑, 哪吒, 问界, 极氪, 小米, 吉利, 长安, 奇瑞, 长城, 五菱, 广汽, 上汽, 北汽, 东风, 江淮, 红旗, 领克, 欧拉, 岚图, 智己, 阿维塔, 腾势, 方程豹, 仰望, 埃安, 深蓝, 启源, 银河, 几何, 蓝电, 捷途, 星途, 猛士, 极越, 极石, 高合, 威马, 天际, 合创, 飞凡, 云度, 朋克, 凌宝, 百智, 金旅, 申龙, 海格, 中通, 金龙, 大通, 福田, 解放, 重汽, 陕汽, 依维柯, 江铃, 庆铃, 王牌, 鑫源, 开瑞, 瑞驰, 华晨, 黄海, 曙光, 新龙马, 卡威, 御捷, 宝雅, 道爵, 速达, 青年, 陆地方舟, 时空, 吉奥, 众泰, 猎豹, 野马, 力帆, 比速, 幻速, 汉腾, 华普, 云雀, 江南, 哈飞, 双环, 中兴, 曙光, 天马, 大地, 万丰, 奥克斯, 波导, 春兰。"""

FEWSHOT = """示例：
Q: 2025年纯电销量前10的车系
SQL: SELECT s.series_name, SUM(f.volume) AS total_volume
     FROM fact_sales_rank f
     JOIN dim_series s ON s.series_id = f.series_id
     JOIN dim_date d ON d.date_id = f.date_id
     WHERE f.new_energy_type = 1 AND d.year = 2025
     GROUP BY s.series_id, s.series_name
     ORDER BY total_volume DESC LIMIT 10

Q: 理想和小米SU7谁卖得多
SQL: SELECT s.series_name, SUM(f.volume) AS total_volume
     FROM fact_sales_rank f
     JOIN dim_series s ON s.series_id = f.series_id
     WHERE s.series_name LIKE '%理想%' OR s.series_name LIKE '%小米SU7%'
     GROUP BY s.series_id, s.series_name
     ORDER BY total_volume DESC

Q: 比亚迪各车系2025年12月的销量
SQL: SELECT s.series_name, f.volume
     FROM fact_sales_rank f
     JOIN dim_series s ON s.series_id = f.series_id
     JOIN dim_brand b ON b.brand_id = s.brand_id
     JOIN dim_date d ON d.date_id = f.date_id
     WHERE b.brand_name LIKE '%比亚迪%' AND d.date_id = 202512
     ORDER BY f.volume DESC

Q: 今年的比亚迪销量如何
SQL: SELECT s.series_name, SUM(f.volume) AS total_volume
     FROM fact_sales_rank f
     JOIN dim_series s ON s.series_id = f.series_id
     JOIN dim_brand b ON b.brand_id = s.brand_id
     JOIN dim_date d ON d.date_id = f.date_id
     WHERE b.brand_name LIKE '%比亚迪%' AND d.year = 2026
     GROUP BY s.series_id, s.series_name
     ORDER BY total_volume DESC

Q: 口碑评分最高的10个车系
SQL: SELECT s.series_name, AVG(r.score) AS avg_score
     FROM fact_review r
     JOIN dim_series s ON s.series_id = r.series_id
     WHERE r.score IS NOT NULL
     GROUP BY s.series_id, s.series_name
     ORDER BY avg_score DESC LIMIT 10

Q: 对比去年同期的数据（上一轮问了2025年纯电销量Top10）
SQL: SELECT s.series_name, SUM(f.volume) AS total_volume_2024
     FROM fact_sales_rank f
     JOIN dim_series s ON s.series_id = f.series_id
     JOIN dim_date d ON d.date_id = f.date_id
     WHERE f.new_energy_type = 1 AND d.year = 2024
     GROUP BY s.series_id, s.series_name
     ORDER BY total_volume_2024 DESC LIMIT 10

Q: 按月拆开看看趋势（上一轮问了比亚迪各车系今年销量）
SQL: SELECT s.series_name, d.ym, SUM(f.volume) AS monthly_volume
     FROM fact_sales_rank f
     JOIN dim_series s ON s.series_id = f.series_id
     JOIN dim_brand b ON b.brand_id = s.brand_id
     JOIN dim_date d ON d.date_id = f.date_id
     WHERE b.brand_name LIKE '%比亚迪%' AND d.year = 2026
     GROUP BY s.series_id, s.series_name, d.ym
     ORDER BY s.series_name, d.ym
"""

SYS = """你是资深数据分析师，把用户问题翻译成一条可执行的 SQL（方言：SQLite 兼容）。
规则：
1. 只输出一条 SELECT 语句，不要解释、不要 markdown 代码块。
2. 只能使用下面给出的表和字段，不要臆造列名。
3. 聚合/分组写清 GROUP BY；按月/年筛选要 JOIN dim_date。
4. 严格遵守给出的领域口径与枚举（如能源类型用数字 1/2/3）。
5. 用户问题中提到的每个品牌、车系名必须出现在 WHERE 子句中（LIKE '%关键词%'）。不得丢弃任何实体。
6. 如果当前问题未提及具体品牌/车系/时间，必须从「近期对话」中提取被省略的实体。例如上一轮问了『奔驰GLC』本轮只问『进一步分析原因』→ 仍然要在 WHERE 中包含奔驰GLC。
7. **时间比较型追问（关键！）**：如果本轮是「对比去年同期」「看趋势」「按月拆开」「对比上个月」等基于上一轮结果的追问：
   - 必须保持上一轮查询的**所有过滤条件**（品牌/车系/能源类型/排名范围）不变，仅调整时间维度或聚合粒度。
   - 例：上一轮「2025年纯电销量Top10的车系」→ 本轮「对比去年同期」→ 改为 year=2024、保持 new_energy_type=1、保持同样的 Top10 排名范围。
   - 例：上一轮「比亚迪各车系今年销量」→ 本轮「按月拆开看趋势」→ 改为 GROUP BY s.series_id, s.series_name, d.ym，保持 brand_name LIKE 比亚迪 和 year=2026。
8. 「今年」指当前年份 2026。
9. 如果用户问的品牌/车系不在上述品牌列表中，说明数据库可能没有该品牌的数据。仍可生成SQL尝试查询，但做好0结果的准备。
"""


def _extract_sql(text: str) -> str:
    text = re.sub(r"```sql|```", "", text, flags=re.I).strip()
    m = re.search(r"(SELECT[\s\S]+)", text, flags=re.I)
    return (m.group(1) if m else text).strip().rstrip(";")


def nl_to_sql_and_run(question: str):
    """返回 dict: {sql, cols, rows, attempts, error}。"""
    schema = link_schema(question)
    messages = [
        {"role": "system", "content": SYS},
        {"role": "user", "content": f"{DOMAIN}\n\n{FEWSHOT}\n可用表结构:\n{schema}\n\nQ: {question}\nSQL:"},
    ]
    last_err = None
    for attempt in range(1, MAX_SQL_RETRY + 2):
        raw = chat(messages, temperature=0.0)
        sql = _extract_sql(raw)
        try:
            sql = with_limit(ensure_safe(sql))
            cols, rows = run_query(sql)
            return {"sql": sql, "cols": cols, "rows": rows, "attempts": attempt, "error": None}
        except (UnsafeSQLError, Exception) as e:  # noqa: 执行/校验错误统一回喂修正
            last_err = str(e)
            # 把错误信息回喂模型，请它修正（自校验重试的关键一步）
            messages.append({"role": "assistant", "content": sql})
            messages.append({"role": "user",
                             "content": f"上面的 SQL 执行报错：{last_err}\n请修正后重新只输出一条 SELECT。"})
    return {"sql": None, "cols": [], "rows": [], "attempts": attempt, "error": last_err}
