"""Regression tests for intent classification rules (deterministic, no LLM).

Tests layer5_business_rules() contract:
- Only sql can be overridden to rag.
- hybrid, rag, chat, clarify are never modified by rules.
"""
from app.nlu import layer5_business_rules


# ── SQL correctly overridden to rag (data not in DB) ──────────────────────────

def test_charging_pile_sql_to_rag():
    assert layer5_business_rules("sql", "截至2026年3月底全国充电桩有多少个") == "rag"


def test_charging_infrastructure_sql_to_rag():
    assert layer5_business_rules("sql", "充电基础设施同比增长了多少") == "rag"


def test_800v_tech_sql_to_rag():
    assert layer5_business_rules("sql", "800V高压平台是怎样的技术趋势") == "rag"


def test_export_sql_to_rag():
    assert layer5_business_rules("sql", "2026年一季度我国汽车整车出口情况如何") == "rag"


def test_charging_public_private_sql_to_rag():
    assert layer5_business_rules("sql", "充电桩里公共和私人各占多少") == "rag"


def test_policy_sql_to_rag():
    assert layer5_business_rules("sql", "最新的新能源购置税政策") == "rag"


# ── SQL stays sql (sales/price/rank queries in DB) ────────────────────────────

def test_brand_sales_stays_sql():
    assert layer5_business_rules("sql", "比亚迪2025年各月销量是多少") == "sql"


def test_model_sales_stays_sql():
    assert layer5_business_rules("sql", "小米SU7一共卖了多少辆") == "sql"


def test_top_n_stays_sql():
    assert layer5_business_rules("sql", "2025年纯电销量前十的车系") == "sql"


def test_yoy_sales_stays_sql():
    assert layer5_business_rules("sql", "2025年插混销量同比增长多少") == "sql"


def test_price_query_stays_sql():
    assert layer5_business_rules("sql", "指导价低于15万的纯电车系有多少个") == "sql"


# ── Hybrid never downgraded (key contract) ────────────────────────────────────

def test_hybrid_with_charging_stays_hybrid():
    assert layer5_business_rules("hybrid", "充电桩分布和销量的关系") == "hybrid"


def test_hybrid_with_export_stays_hybrid():
    assert layer5_business_rules("hybrid", "出口数据和国内销量对比分析") == "hybrid"


def test_hybrid_with_800v_stays_hybrid():
    assert layer5_business_rules("hybrid", "800V车型销量和技术优势分析") == "hybrid"


def test_hybrid_with_policy_stays_hybrid():
    assert layer5_business_rules("hybrid", "补贴政策对销量的影响分析") == "hybrid"


def test_hybrid_with_analysis_stays_hybrid():
    assert layer5_business_rules("hybrid", "哪些品牌销量领先，它们各自有什么特征") == "hybrid"


def test_hybrid_with_why_stays_hybrid():
    assert layer5_business_rules("hybrid", "星愿销量多少，为什么卖这么好") == "hybrid"


# ── rag never modified ────────────────────────────────────────────────────────

def test_rag_with_policy_stays_rag():
    assert layer5_business_rules("rag", "购置税补贴政策有哪些") == "rag"


def test_rag_stays_rag():
    assert layer5_business_rules("rag", "800V高压平台技术解读") == "rag"


# ── chat and clarify never modified ───────────────────────────────────────────

def test_chat_not_modified():
    assert layer5_business_rules("chat", "你好") == "chat"


def test_clarify_not_modified():
    assert layer5_business_rules("clarify", "充电桩数量") == "clarify"
