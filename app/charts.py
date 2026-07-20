"""图表描述符（规则引擎，不再用 LLM）。

设计变更（2026-05-22）：后端不再生成「写死的 ECharts option」，改为产出**图表描述符**——
告诉前端「用哪一列当维度、哪些列当数值系列、默认/可选图型、标题」，前端配合 rows 自由拼图、
切换图型、显示图例。规则引擎看结果集结构（有没有时间列、几个维度、类别多少）判图型，
比 LLM 更快更稳；LLM 只留给结论/归因（insights）。

契约（与前端对齐）：
{
  "default_type": "bar",                       # 首选图型
  "applicable_types": ["bar","hbar","line","pie"],  # 可切换图型（前端出切换按钮）
  "dimension": "series_name",                  # 维度列：x 轴 / 饼图类别
  "measures": ["volume"],                      # 数值列：系列(可多个 → 多系列 + 图例)
  "title": "..."
}
图型名：bar(竖向柱) / hbar(横向条，类别多时友好) / line(折线，含时间维度) / pie(占比，单系列少类别)。
前端按 measures 个数决定系列数与图例项，按 dimension 决定 x 轴/饼图类别，数据全取自 rows。
"""
import re

# 列名像时间维度（年/月/季/日期）— 用词边界避免 monthly_volume 误匹配
_TIME_NAME = re.compile(r"(?:^|_)(year|month|quarter|date|time|ym|day)(?:$|_)|[年月季周日期时间]", re.I)
# 列名含度量关键词时不算时间维度（即使包含 month/year 子串）
_MEASURE_NAME = re.compile(r"(volume|count|sum|amount|total|rank|sales|price|avg|rate|ratio|num|qty)", re.I)
# 取值像 年月：2025-05 / 202505 / 2025/05 / 2025-05-01
_YM_VALUE = re.compile(r"^\d{4}[-/]?\d{1,2}([-/]\d{1,2})?$")

PIE_MAX_CATEGORIES = 8     # 类别 ≤ 此值且单系列，才把 pie 列为可选
HBAR_MIN_CATEGORIES = 12   # 类别 > 此值，默认横向条形（Top-N 友好）


def _is_number(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v.replace(",", ""))
            return True
        except ValueError:
            return False
    return False


def recommend_chart(cols, rows, question: str = ""):
    """看结果集结构产出图表描述符；无法成图返回 table 描述符。"""
    if not cols or not rows:
        return None

    # —— 逐列判定：数值？时间？——（rows 为 dict 行）
    numeric, timelike = {}, {}
    for c in cols:
        vals = [r.get(c) for r in rows if r.get(c) is not None]
        numeric[c] = bool(vals) and all(_is_number(v) for v in vals)
        is_measure_name = bool(_MEASURE_NAME.search(str(c)))
        name_is_time = bool(_TIME_NAME.search(str(c))) and not is_measure_name
        val_is_time = bool(vals) and all(isinstance(v, str) and _YM_VALUE.match(v.strip()) for v in vals)
        timelike[c] = name_is_time or val_is_time

    # 数值系列 = 数值列且非时间列（year/month 这种数值时间列算维度，不算度量）
    measures = [c for c in cols if numeric[c] and not timelike[c]]
    time_cols = [c for c in cols if timelike[c]]
    text_cols = [c for c in cols if not numeric[c] and not timelike[c]]

    title = (question or "").strip() or "查询结果"

    # 没有可度量的数值列 → 只能看表，不出图
    if not measures:
        return {"default_type": "table", "applicable_types": ["table"],
                "dimension": (cols[0] if cols else None), "measures": [], "title": title}

    # —— 选维度 + 判图型 ——
    # 优先用「类别维度」（文本列）做对比；只有时间列时才走趋势折线。
    if text_cols:
        dimension = text_cols[0]
        n_cat = len({r.get(dimension) for r in rows})
        if n_cat > HBAR_MIN_CATEGORIES:
            default_type, applicable = "hbar", ["hbar", "bar", "line"]
        else:
            default_type, applicable = "bar", ["bar", "hbar", "line"]
        if len(measures) == 1 and n_cat <= PIE_MAX_CATEGORIES:
            applicable.append("pie")          # 单系列、少类别才适合饼图
    elif time_cols:
        dimension = time_cols[0]
        default_type, applicable = "line", ["line", "bar"]
    else:
        # 既无文本也无时间维度（如单行聚合值）：给柱形兜底，维度留空由前端决定怎么展示
        dimension = None
        default_type, applicable = "bar", ["bar", "table"]

    return {
        "default_type": default_type,
        "applicable_types": applicable,
        "dimension": dimension,
        "measures": measures,
        "title": title,
    }
