"""Text2SQL 核心：组装 Prompt（schema + few-shot）→ 生成 SQL → 安全校验
→ 执行 → 出错则把错误回喂模型自动修正（见技术设计第 4 节）。"""
import re
import time
from functools import lru_cache
from .llm import chat
from .db import run_query
from .sql_guard import ensure_safe, with_limit, UnsafeSQLError
from .schema_linking import link_schema
from .config import CATALOG_CACHE_TTL_SECONDS, MAX_SQL_RETRY

# 领域提示：把懂车帝销量榜星型模型的语义/枚举喂给 LLM（schema introspection 只给类型，缺业务含义）
DOMAIN = """库为「车市镜」新能源汽车销量分析库（懂车帝榜单，全国口径，月粒度）。星型模型：
- dim_series(series_id, series_name 车系名如「小米SU7」「理想L6」, brand_id, powertrain 动力 纯电/插混/增程, guide_price_min/max 指导价万元)
- dim_brand(brand_id, brand_name 品牌名如「理想汽车」「比亚迪」)
- dim_date(date_id=YYYYMM 整数如 202505, year, month, quarter, ym 形如 '2025-05')。按年/月筛选优先 JOIN dim_date 用 year/month 字段，也可在明确年月时使用 date_id=YYYYMM
- fact_sales_rank(series_id, date_id, new_energy_type 能源类型[1纯电/2插混/3增程], rank 当月排名, last_rank 上期排名[NULL=新上榜], volume 销量[核心度量,单位辆])
- fact_price(series_id, date_id, guide_price_min/max, dealer_price_text 经销商报价, descender_price 降价幅度)
- fact_review(series_id, date_id, review_count 口碑数, score 口碑评分[0-5分，部分车系为NULL])
关键口径：
- 「销量」=fact_sales_rank.volume，跨月需 SUM；某月销量需 JOIN dim_date 按 year/month 过滤。
- 能源类型用 fact_sales_rank.new_energy_type 数字过滤：纯电=1、插混=2、增程=3。注意 dim_series.powertrain 存的也是 '纯电'/'插混'/'增程' 文本，但做能源类型聚合/分组时应使用 fact_sales_rank.new_energy_type。
- 车系名/品牌名模糊匹配用 LIKE '%关键词%'。当前年份：2026。
- 品牌名匹配注意：优先把用户原话中能在 dim_brand 命中的完整品牌作为一个整体匹配。例如「吉利银河」是独立品牌，必须用 b.brand_name LIKE '%吉利银河%'，不能拆成「吉利汽车」品牌 + series_name LIKE '%银河%'。只有完整品牌无法命中时，才使用最短唯一前缀（如 '%理想%'、'%五菱%'）。
- 问「XX累计销量」时只需返回汇总数值（SELECT SUM(...) v），不需要额外输出车系/品牌名列；若问题没有指定年份/月度，累计=库内全部月份，禁止擅自加当前年份过滤。
- 问「哪个品牌销量最高」必须返回 brand_name + 聚合销量，按品牌 GROUP BY、销量 DESC、LIMIT 1，不能只返回 MAX(销量) 而丢失品牌名。
- fact_sales_rank.rank 是纯电/插混/增程各分区内部的月榜名次。用户没有指定能源类型时，「销量第一/销量最高/卖得最多的车系」不能用 rank=1；单月应按 volume DESC，跨月应按车系 SUM(volume) 后降序。
- 指导价区间按“整个车系”解释：「低于X万」用 guide_price_max<X；「X万以上」用 guide_price_min>=X。
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

Q: 海鸥2025年累计销量
SQL: SELECT SUM(f.volume) AS total_volume
     FROM fact_sales_rank f
     JOIN dim_series s ON s.series_id = f.series_id
     JOIN dim_date d ON d.date_id = f.date_id
     WHERE s.series_name LIKE '%海鸥%' AND d.year = 2025

Q: 理想汽车全系2025年累计销量
SQL: SELECT SUM(f.volume) AS total_volume
     FROM fact_sales_rank f
     JOIN dim_series s ON s.series_id = f.series_id
     JOIN dim_brand b ON b.brand_id = s.brand_id
     JOIN dim_date d ON d.date_id = f.date_id
     WHERE b.brand_name LIKE '%理想%' AND d.year = 2025

Q: 2025年各动力类型的总销量
SQL: SELECT f.new_energy_type, SUM(f.volume) AS total_volume
     FROM fact_sales_rank f
     JOIN dim_date d ON d.date_id = f.date_id
     WHERE d.year = 2025
     GROUP BY f.new_energy_type
     ORDER BY f.new_energy_type

Q: 2025年纯电、插混、增程各有多少款车系上榜
SQL: SELECT f.new_energy_type, COUNT(DISTINCT f.series_id) AS series_count
     FROM fact_sales_rank f
     JOIN dim_date d ON d.date_id = f.date_id
     WHERE d.year = 2025 AND f.new_energy_type IN (1, 2, 3)
     GROUP BY f.new_energy_type
     ORDER BY f.new_energy_type

Q: 哪个品牌2025年新能源累计销量最高
SQL: SELECT b.brand_name, SUM(f.volume) AS total_volume
     FROM fact_sales_rank f
     JOIN dim_series s ON s.series_id = f.series_id
     JOIN dim_brand b ON b.brand_id = s.brand_id
     JOIN dim_date d ON d.date_id = f.date_id
     WHERE d.year = 2025
     GROUP BY b.brand_id, b.brand_name
     ORDER BY total_volume DESC LIMIT 1

Q: 比亚迪和吉利银河谁2025年新能源销量更高
SQL: SELECT b.brand_name, SUM(f.volume) AS total_volume
     FROM fact_sales_rank f
     JOIN dim_series s ON s.series_id = f.series_id
     JOIN dim_brand b ON b.brand_id = s.brand_id
     JOIN dim_date d ON d.date_id = f.date_id
     WHERE b.brand_name IN ('比亚迪', '吉利银河') AND d.year = 2025
     GROUP BY b.brand_id, b.brand_name
     ORDER BY total_volume DESC

Q: AION Y累计销量
SQL: SELECT SUM(f.volume) AS total_volume
     FROM fact_sales_rank f
     JOIN dim_series s ON s.series_id = f.series_id
     WHERE s.series_name LIKE '%AION Y%'

Q: 指导价低于15万的纯电车系有多少个
SQL: SELECT COUNT(*) AS series_count
     FROM dim_series s
     WHERE s.powertrain = '纯电' AND s.guide_price_max < 15

Q: 指导价30万以上的车系有多少个
SQL: SELECT COUNT(*) AS series_count
     FROM dim_series s
     WHERE s.guide_price_min >= 30

Q: 2025年每月纯电总销量趋势
SQL: SELECT d.ym, SUM(f.volume) AS total_volume
     FROM fact_sales_rank f
     JOIN dim_date d ON d.date_id = f.date_id
     WHERE d.year = 2025 AND f.new_energy_type = 1
     GROUP BY d.ym
     ORDER BY d.ym

Q: 2025年12月排名上升的车系有哪些
SQL: SELECT s.series_name, f.rank, f.last_rank
     FROM fact_sales_rank f
     JOIN dim_series s ON s.series_id = f.series_id
     JOIN dim_date d ON d.date_id = f.date_id
     WHERE d.year = 2025 AND d.month = 12
       AND f.last_rank IS NOT NULL AND f.rank < f.last_rank
     ORDER BY (f.last_rank - f.rank) DESC

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
10. 「累计销量/总销量/一共卖了多少」默认只返回一个 SUM 汇总值；只有问题明确要求「各车系/分别/对比/排行」时才 GROUP BY 返回多行。若问题未指定年份/月度，累计指库内全部月份，禁止擅自用当前年份 2026 过滤。
11. 「排名上升/下降/优于上期」必须同时检查 last_rank IS NOT NULL，并比较 rank 与 last_rank。
12. 「哪个品牌/哪家品牌销量最高」必须 SELECT brand_name 与 SUM(volume)，按品牌 GROUP BY、销量 DESC、LIMIT 1，不能 SELECT MAX(...) 丢掉冠军是谁。
13. 「低于X万」按车系最高指导价 guide_price_max<X；「X万以上」按车系最低指导价 guide_price_min>=X。
14. 「每月/按月/月度趋势」必须 SELECT 并 GROUP BY dim_date.ym，按 ym 排序。
15. 同时比较纯电/插混/增程时，用 new_energy_type 分组返回多行；不要把多个类别压成一行，也不要遗漏类别。
16. 如果提示中给出「数据库完整品牌命中」，每个命中项都必须作为一个整体过滤 dim_brand.brand_name；不得把复合品牌拆成母品牌 + 车系关键词。
17. rank 是能源类型分区内的月榜名次。未指定纯电/插混/增程时，「销量第一/销量最高/卖得最多的车系」严禁用 rank=1：单月按 volume DESC LIMIT 1，跨月按车系 GROUP BY 后 SUM(volume) DESC LIMIT 1。
"""


def _catalog_cache_bucket() -> int:
    return int(time.monotonic() // CATALOG_CACHE_TTL_SECONDS)


@lru_cache(maxsize=2)
def _load_brand_catalog(_bucket: int) -> tuple[str, ...]:
    """Use the analysis database as the source of truth for brand entity names."""
    try:
        _, rows = run_query(
            "SELECT DISTINCT brand_name FROM dim_brand "
            "WHERE brand_name IS NOT NULL AND brand_name <> ''",
            limit=5000,
        )
    except Exception:
        return ()
    names = {
        str(row.get("brand_name") or "").strip()
        for row in rows
        if str(row.get("brand_name") or "").strip()
    }
    return tuple(sorted(names, key=len, reverse=True))


def _brand_catalog() -> tuple[str, ...]:
    return _load_brand_catalog(_catalog_cache_bucket())


@lru_cache(maxsize=2)
def _load_series_catalog(_bucket: int) -> tuple[str, ...]:
    """Known series names are used to avoid treating substrings as brands."""
    try:
        _, rows = run_query(
            "SELECT DISTINCT series_name FROM dim_series "
            "WHERE series_name IS NOT NULL AND series_name <> ''",
            limit=5000,
        )
    except Exception:
        return ()
    names = {
        str(row.get("series_name") or "").strip()
        for row in rows
        if str(row.get("series_name") or "").strip()
    }
    return tuple(sorted(names, key=len, reverse=True))


def _series_catalog() -> tuple[str, ...]:
    return _load_series_catalog(_catalog_cache_bucket())


def clear_catalog_caches() -> None:
    """Explicit invalidation hook for loaders/tests running in this process."""
    _load_brand_catalog.cache_clear()
    _load_series_catalog.cache_clear()


def _matching_spans(text: str, token: str) -> list[tuple[int, int]]:
    return [
        (match.start(), match.end())
        for match in re.finditer(re.escape(token.lower()), text.lower())
    ]


def _exact_brand_names(question: str) -> tuple[str, ...]:
    """Return brand mentions that are not merely substrings of a known series."""
    q = (question or "").strip().lower()
    if not q:
        return ()
    series_spans = [
        span
        for series_name in _series_catalog()
        if series_name.lower() in q
        for span in _matching_spans(q, series_name)
    ]
    matches = []
    for brand_name in _brand_catalog():
        brand_spans = _matching_spans(q, brand_name)
        if not brand_spans:
            continue
        # "五菱宏光MINIEV" contains the real brand "MINI", but the only
        # occurrence is part of the complete series entity and must not become
        # an independent brand filter. An occurrence outside a series span is
        # still a genuine brand mention.
        if all(
            any(series_start <= start and end <= series_end
                for series_start, series_end in series_spans)
            for start, end in brand_spans
        ):
            continue
        matches.append(brand_name)
    return tuple(matches)


def _brand_entity_hint(question: str) -> str:
    names = _exact_brand_names(question)
    if not names:
        return ""
    return (
        "数据库完整品牌命中（以下每项都是 dim_brand.brand_name 中的独立品牌，"
        "必须整体匹配 brand_name，禁止拆到 series_name）："
        f"{', '.join(names)}\n\n"
    )


def _extract_sql(text: str) -> str:
    text = re.sub(r"```sql|```", "", text, flags=re.I).strip()
    m = re.search(r"(SELECT[\s\S]+)", text, flags=re.I)
    return (m.group(1) if m else text).strip().rstrip(";")


def nl_to_sql_and_run(question: str):
    """返回 dict: {sql, cols, rows, attempts, error}。"""
    schema = link_schema(question)
    messages = [
        {"role": "system", "content": SYS},
        {"role": "user", "content": (
            f"{DOMAIN}\n\n{_brand_entity_hint(question)}{FEWSHOT}\n"
            f"可用表结构:\n{schema}\n\nQ: {question}\nSQL:"
        )},
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
