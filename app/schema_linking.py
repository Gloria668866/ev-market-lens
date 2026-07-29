"""Schema Linking：表/列很多时，先挑出与问题相关的表，只把相关 schema 喂给 LLM。

升级点：
- 原关键词匹配 = 中文问题 vs 英文表名，命中率极低（"口碑" 无法匹配 "fact_review"）
- 现在：语义描述匹配 + 实体信号增强 + 列名匹配三层叠加
"""
from .db import get_schema_snapshot

# 每张表的中文语义描述——解决「中文问题 vs 英文表名」的核心矛盾
_TABLE_SEMANTIC = {
    "dim_series":       "车系 车型 车名 型号 车款 款型",
    "dim_brand":        "品牌 厂商 车企 汽车公司 车厂",
    "dim_date":         "时间 年份 月份 季度 日期 年月",
    "fact_sales_rank":  "销量 排名 卖 畅销 热销 top 新能源 纯电 插混 增程 月度 同比 环比 趋势",
    "fact_price":       "价格 报价 优惠 降价 涨价 指导价 经销商 万元 贵 便宜",
    "fact_review":      "口碑 评分 评价 用户反馈 满意度 好评 差评 评测 体验",
}

# 实体类型 → 必然关联的表（实体存在即强制拉入）
_ENTITY_TABLE_AFFINITY = {
    "brands": {"dim_brand", "dim_series", "fact_sales_rank", "fact_price", "fact_review"},
    "models": {"dim_series", "fact_sales_rank", "fact_price", "fact_review"},
    "time":   {"dim_date", "fact_sales_rank", "fact_price", "fact_review"},
    "metrics_sales":  {"fact_sales_rank"},
    "metrics_price":  {"fact_price"},
    "metrics_review": {"fact_review"},
}


def _entity_table_boost(tbl: str, entities: dict) -> int:
    """实体存在时给相关表加权，确保必要的表不被遗漏。"""
    boost = 0
    for etype, tables in _ENTITY_TABLE_AFFINITY.items():
        if tbl not in tables:
            continue
        if etype == "brands" and (entities.get("brands") or entities.get("models")):
            boost += 3
        elif etype == "time" and entities.get("time"):
            boost += 2
        elif etype == "metrics_sales" and any(
            k in str(entities.get("metrics", [])) for k in ("销量", "排名", "卖", "趋势")
        ):
            boost += 4
        elif etype == "metrics_price" and any(
            k in str(entities.get("metrics", [])) for k in ("价格", "报价", "降价")
        ):
            boost += 4
        elif etype == "metrics_review" and any(
            k in str(entities.get("metrics", [])) for k in ("口碑", "评分", "评价", "满意")
        ):
            boost += 4
    return boost


def link_schema(question: str, entities: dict = None, max_tables: int = 6) -> str:
    """
    三层语义匹配：
    1. 语义描述匹配（中文关键词 vs 中文描述，解决表名英文问题）
    2. 实体信号增强（已提取实体直接拉入相关表）
    3. 列名兜底（原有逻辑保留）
    """
    full_schema, meta = get_schema_snapshot()
    if len(meta) <= max_tables:
        return full_schema

    q = question.lower()
    entities = entities or {}
    scored = []

    for tbl, cols in meta.items():
        # 层1：语义描述匹配
        desc = _TABLE_SEMANTIC.get(tbl, "")
        sem_score = sum(1 for tok in desc.split() if tok and tok in q)

        # 层2：实体信号增强
        ent_boost = _entity_table_boost(tbl, entities)

        # 层3：英文列名兜底（处理用户输入英文关键词的情况）
        col_score = sum(1 for c in cols if c.lower() in q)

        total = sem_score + ent_boost + col_score
        scored.append((total, tbl, cols))

    scored.sort(reverse=True)
    # 有得分的优先；全零时退化到全量（小库场景）
    picked = [s for s in scored if s[0] > 0][:max_tables] or scored[:max_tables]
    return "\n".join(f"TABLE {t}({', '.join(cols)})" for _, t, cols in picked)
