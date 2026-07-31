"""Regression tests for intent classification rules (deterministic, no LLM).

Tests layer5_business_rules() contract:
- Only sql can be overridden to rag.
- hybrid, rag, chat, clarify are never modified by rules.
"""
import pytest

from app.nlu import deterministic_intent_hint, layer5_business_rules


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


@pytest.mark.parametrize("question", [
    "30万以上价位卖得最好的车系排名",
    "排名环比上升最快的车系",
    "哪些车系每个月都进了前十",
    "增程SUV销量前五",
])
def test_deterministic_sql_hints(question):
    assert deterministic_intent_hint(question) == "sql"


@pytest.mark.parametrize("question", [
    "理想i8的车主口碑怎么样",
    "长安汽车的1445战略是什么",
    "比亚迪在动力电池回收方面做了什么",
    "这份年度报告怎么看2025年的价格带格局",
    "报告对2025年销量总览是怎么说的",
    "报告认为新能源价格战会怎么发展",
])
def test_deterministic_rag_hints(question):
    assert deterministic_intent_hint(question) == "rag"


@pytest.mark.parametrize("question", [
    "充电基础设施同比增长了多少",
    "用户对新能源车的售后体验评价怎样",
])
def test_out_of_schema_metrics_and_review_language_route_to_rag(question):
    assert deterministic_intent_hint(question) == "rag"


@pytest.mark.parametrize("question", [
    "小米SU7卖得怎么样，口碑好不好",
    "理想L6销量多少，车主评价如何",
    "10到20万卖得最好的车有哪些，报告怎么分析这个区间",
    "插混销量趋势怎样，相关政策有什么影响",
    "比亚迪各车系卖多少，口碑上大家怎么说",
    "增程车销量数据如何，报告怎么解读这个趋势",
    "2025销量冠军是谁，报告怎么评价它",
    "30万以上市场销量格局如何，报告怎么解读",
])
def test_deterministic_hybrid_hints(question):
    assert deterministic_intent_hint(question) == "hybrid"


@pytest.mark.parametrize(
    "question",
    [
        "有什么想法吗",
        "这个靠谱吗",
        "你觉得呢",
        "这几个里面选哪个",
        "帮我参考一下",
    ],
)
def test_deterministic_vague_hints_without_context(question):
    assert deterministic_intent_hint(question) == "clarify"


def test_short_generic_sales_phrase_is_not_forced_to_sql():
    assert deterministic_intent_hint("销量排名") is None


def test_dynamic_top_n_aggregate_is_forced_to_sql():
    assert deterministic_intent_hint("各品牌进入销量前50的车系数量") == "sql"


@pytest.mark.parametrize(
    "question",
    [
        "现在买什么车合适",
        "我应该选什么车",
        "推荐什么车",
    ],
)
def test_underspecified_purchase_recommendation_requires_clarification(question):
    assert deterministic_intent_hint(question) == "clarify"


def test_scoped_purchase_recommendation_is_not_forced_to_clarify():
    assert deterministic_intent_hint("预算20万，家用应该买什么车") != "clarify"
