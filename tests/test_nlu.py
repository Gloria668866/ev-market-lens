"""Unit tests for app/nlu.py — layers that don't need LLM."""
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _disable_real_few_shot_model_loading(monkeypatch):
    """NLU unit tests must never load the heavyweight BGE model."""
    from app import nlu

    monkeypatch.setattr(nlu, "_few_shot_initialized", True)


# ── Layer 1 ───────────────────────────────────────────────────────────────────

def test_layer1_greeting_short():
    from app.nlu import layer1_prefilter
    result = layer1_prefilter("你好", "")
    assert result is not None
    assert result["intent"] == "chat"
    assert result["source"] == "layer1_greeting"


def test_layer1_greeting_long_not_triggered():
    from app.nlu import layer1_prefilter
    result = layer1_prefilter("你好，比亚迪今年卖了多少", "")
    assert result is None


def test_layer1_greeting_plus_business_entity_is_not_chat():
    from app.nlu import layer1_prefilter

    assert layer1_prefilter("你好比亚迪", "") is None


def test_layer1_no_data_signal_sets_force_rag():
    from app.nlu import layer1_prefilter
    result = layer1_prefilter("进一步分析", "未查询到相关数据，请换个问法")
    assert result is not None
    assert result.get("force_rag") is True


def test_layer1_no_signal_returns_none():
    from app.nlu import layer1_prefilter
    result = layer1_prefilter("比亚迪销量", "比亚迪2025年销量为120万辆")
    assert result is None


# ── Layer 4 ───────────────────────────────────────────────────────────────────

def test_layer4_sql_with_brand_is_complete():
    from app.nlu import layer4_check_completeness
    ok, slots = layer4_check_completeness("sql", {"brands": ["比亚迪"]}, "比亚迪销量")
    assert ok is True
    assert slots == []


def test_layer4_sql_with_metric_keyword_is_complete():
    from app.nlu import layer4_check_completeness
    ok, slots = layer4_check_completeness("sql", {}, "2025年纯电Top10")
    assert ok is True


def test_layer4_sql_no_entity_no_keyword_incomplete():
    from app.nlu import layer4_check_completeness
    ok, slots = layer4_check_completeness("sql", {}, "哪个好")
    assert ok is False
    assert len(slots) > 0


def test_layer4_rag_always_complete():
    from app.nlu import layer4_check_completeness
    ok, slots = layer4_check_completeness("rag", {}, "为什么")
    assert ok is True


def test_layer4_chat_always_complete():
    from app.nlu import layer4_check_completeness
    ok, slots = layer4_check_completeness("chat", {}, "你好")
    assert ok is True


# ── Layer 5 ───────────────────────────────────────────────────────────────────

def test_layer5_policy_keyword_forces_rag():
    from app.nlu import layer5_business_rules
    assert layer5_business_rules("sql", "最新的新能源购置税政策") == "rag"


def test_layer5_subsidy_hybrid_not_downgraded():
    from app.nlu import layer5_business_rules
    assert layer5_business_rules("hybrid", "比亚迪能享受哪些补贴") == "hybrid"


def test_layer5_subsidy_sql_forces_rag():
    from app.nlu import layer5_business_rules
    assert layer5_business_rules("sql", "比亚迪能享受哪些补贴") == "rag"


def test_layer5_no_rule_match_unchanged():
    from app.nlu import layer5_business_rules
    assert layer5_business_rules("sql", "比亚迪2025年销量") == "sql"


# ── Confidence gate ───────────────────────────────────────────────────────────

def test_confidence_gate_passes_high():
    from app.nlu import _confidence_gate
    assert _confidence_gate({"confidence": 0.95, "top2_confidence": 0.10}) is True


def test_confidence_gate_fails_low_confidence():
    from app.nlu import _confidence_gate
    assert _confidence_gate({"confidence": 0.60, "top2_confidence": 0.20}) is False


def test_confidence_gate_fails_ambiguous():
    from app.nlu import _confidence_gate
    # gap = 0.75 - 0.65 = 0.10 < threshold 0.15
    assert _confidence_gate({"confidence": 0.75, "top2_confidence": 0.65}) is False


# ── Layer 2 ───────────────────────────────────────────────────────────────────

def test_layer2_classify_sql(monkeypatch):
    from app import nlu
    monkeypatch.setattr(nlu, "_few_shot_embeddings", None)
    monkeypatch.setattr(nlu, "_few_shot_examples", None)
    with patch("app.nlu.chat", return_value='{"intent":"sql","confidence":0.95,"top2_intent":"hybrid","top2_confidence":0.08}'):
        result = nlu.layer2_classify("比亚迪2025年销量", "")
    assert result["intent"] == "sql"
    assert result["confidence"] == 0.95
    assert result["source"] == "layer2_llm"


def test_layer2_classify_force_rag_overrides_sql(monkeypatch):
    from app import nlu
    monkeypatch.setattr(nlu, "_few_shot_embeddings", None)
    monkeypatch.setattr(nlu, "_few_shot_examples", None)
    with patch("app.nlu.chat", return_value='{"intent":"sql","confidence":0.90,"top2_intent":"rag","top2_confidence":0.10}'):
        result = nlu.layer2_classify("进一步分析", "", force_rag=True)
    assert result["intent"] == "rag"


def test_layer2_classify_llm_error_returns_clarify(monkeypatch):
    from app import nlu
    monkeypatch.setattr(nlu, "_few_shot_embeddings", None)
    monkeypatch.setattr(nlu, "_few_shot_examples", None)
    with patch("app.nlu.chat", side_effect=Exception("timeout")):
        result = nlu.layer2_classify("比亚迪销量", "")
    assert result["intent"] == "clarify"
    assert result["source"] == "layer2_fallback"


def test_layer2_rejects_wrong_entity_types_in_model_json(monkeypatch):
    from app import nlu

    bad = (
        '{"intent":"sql","confidence":0.95,"top2_intent":"rag",'
        '"top2_confidence":0.05,"brands":"比亚迪","time":2025}'
    )
    with patch("app.nlu.chat", return_value=bad):
        result = nlu.layer2_analyze("比亚迪2025年销量")

    assert result["intent"] == "clarify"
    assert result["source"] == "layer2_fallback"
    assert result["brands"] == []


def test_layer2_rejects_out_of_range_confidence(monkeypatch):
    from app import nlu

    with patch(
        "app.nlu.chat",
        return_value='{"intent":"sql","confidence":1.4,"top2_confidence":0}',
    ):
        result = nlu.layer2_analyze("比亚迪销量")

    assert result["intent"] == "clarify"
    assert result["source"] == "layer2_fallback"


def test_layer2_few_shot_retrieval_returns_examples(monkeypatch):
    import numpy as np
    from app import nlu
    fake_emb = np.random.rand(3, 4).astype(np.float32)
    # normalize
    fake_emb = fake_emb / np.linalg.norm(fake_emb, axis=1, keepdims=True)
    fake_examples = [
        {"question": "比亚迪销量", "intent": "sql"},
        {"question": "口碑怎么样", "intent": "rag"},
        {"question": "你好", "intent": "chat"},
    ]
    monkeypatch.setattr(nlu, "_few_shot_embeddings", fake_emb)
    monkeypatch.setattr(nlu, "_few_shot_examples", fake_examples)

    query_vec = np.random.rand(4).astype(np.float32)
    query_vec = query_vec / np.linalg.norm(query_vec)
    with patch("app.nlu.embed_query", return_value=query_vec.tolist()):
        results = nlu._retrieve_few_shot("销量", top_k=2)
    assert len(results) == 2
    assert all("intent" in r for r in results)


# ── Layer 3 ───────────────────────────────────────────────────────────────────

def test_layer3_extracts_brand(monkeypatch):
    from app import nlu
    with patch("app.nlu.chat", return_value='{"brands":["比亚迪"],"models":[],"time":["2025年"],"metrics":[],"energy_types":[],"normalized_question":"比亚迪2025年销量"}'):
        result = nlu.layer3_extract_entities("比亚迪2025年销量", "")
    assert result["brands"] == ["比亚迪"]
    assert result["time"] == ["2025年"]
    assert result["normalized_question"] == "比亚迪2025年销量"


def test_layer3_llm_error_returns_empty(monkeypatch):
    from app import nlu
    with patch("app.nlu.chat", side_effect=Exception("timeout")):
        result = nlu.layer3_extract_entities("比亚迪销量", "")
    assert result["brands"] == []
    assert result["normalized_question"] == "比亚迪销量"


# ── classify() 完整流程 ────────────────────────────────────────────────────────

def test_classify_full_sql_flow(monkeypatch):
    from app import nlu
    monkeypatch.setattr(nlu, "_few_shot_embeddings", None)
    monkeypatch.setattr(nlu, "_few_shot_examples", None)

    classify_resp = '{"intent":"sql","confidence":0.92,"top2_intent":"hybrid","top2_confidence":0.05}'
    entity_resp = '{"brands":["比亚迪"],"models":[],"time":["2025年"],"metrics":[],"energy_types":[],"normalized_question":"比亚迪2025年销量"}'

    call_count = {"n": 0}
    def mock_chat(msgs, **kw):
        call_count["n"] += 1
        return classify_resp if call_count["n"] == 1 else entity_resp

    with patch("app.nlu.chat", side_effect=mock_chat):
        result = nlu.classify("比亚迪2025年销量")

    assert result["intent"] == "sql"
    assert result["entities"]["brands"] == ["比亚迪"]
    assert result["is_complete"] is True
    assert result["missing_slots"] == []


def test_classify_incomplete_sql_becomes_clarify(monkeypatch):
    from app import nlu
    monkeypatch.setattr(nlu, "_few_shot_embeddings", None)
    monkeypatch.setattr(nlu, "_few_shot_examples", None)

    classify_resp = '{"intent":"sql","confidence":0.88,"top2_intent":"clarify","top2_confidence":0.05}'
    entity_resp = '{"brands":[],"models":[],"time":[],"metrics":[],"energy_types":[],"normalized_question":"哪个好"}'

    call_count = {"n": 0}
    def mock_chat(msgs, **kw):
        call_count["n"] += 1
        return classify_resp if call_count["n"] == 1 else entity_resp

    with patch("app.nlu.chat", side_effect=mock_chat):
        result = nlu.classify("哪个好")

    assert result["intent"] == "clarify"
    assert len(result["missing_slots"]) > 0


def test_classify_policy_question_forced_rag(monkeypatch):
    from app import nlu
    monkeypatch.setattr(nlu, "_few_shot_embeddings", None)
    monkeypatch.setattr(nlu, "_few_shot_examples", None)

    classify_resp = '{"intent":"sql","confidence":0.85,"top2_intent":"rag","top2_confidence":0.10}'
    entity_resp = '{"brands":[],"models":[],"time":[],"metrics":[],"energy_types":[],"normalized_question":"购置税政策"}'

    call_count = {"n": 0}
    def mock_chat(msgs, **kw):
        call_count["n"] += 1
        return classify_resp if call_count["n"] == 1 else entity_resp

    with patch("app.nlu.chat", side_effect=mock_chat):
        result = nlu.classify("最新的购置税政策有哪些")

    assert result["intent"] == "rag"


def test_classify_low_confidence_becomes_clarify(monkeypatch):
    from app import nlu
    monkeypatch.setattr(nlu, "_few_shot_embeddings", None)
    monkeypatch.setattr(nlu, "_few_shot_examples", None)

    classify_resp = '{"intent":"sql","confidence":0.55,"top2_intent":"rag","top2_confidence":0.40}'

    with patch("app.nlu.chat", return_value=classify_resp):
        result = nlu.classify("那个数据")

    assert result["intent"] == "clarify"
    assert result["source"] == "confidence_gate"


def test_classify_chat_greeting_shortcircuits_before_llm(monkeypatch):
    from app import nlu
    monkeypatch.setattr(nlu, "_few_shot_embeddings", None)
    monkeypatch.setattr(nlu, "_few_shot_examples", None)
    with patch("app.nlu.chat") as mock_chat:
        result = nlu.classify("你好", last_assistant="")
    assert result["intent"] == "chat"
    assert result["confidence"] == 1.0
    assert result["llm_calls"] == 0
    assert result["nlu_latency_ms"] >= 0
    mock_chat.assert_not_called()


def test_classify_deterministic_sql_uses_zero_nlu_model_calls():
    from app import nlu

    with patch("app.nlu.chat") as mock_chat:
        result = nlu.classify("比亚迪2025年销量")

    assert result["intent"] == "sql"
    assert result["entities"]["brands"] == ["比亚迪"]
    assert result["entities"]["time"] == ["2025年"]
    assert result["llm_calls"] == 0
    mock_chat.assert_not_called()


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("纯电中型SUV销量排名", "sql"),
        ("Model Y销量如何，用户怎么评价", "hybrid"),
        ("纯电车续航现在到什么水平，销量靠前的有哪些", "hybrid"),
        ("理想全系销量多少，行业对增程怎么看", "hybrid"),
        ("午饭吃什么", "chat"),
        ("谢谢你的帮助", "chat"),
        ("给我讲个笑话", "chat"),
        ("你能做什么", "chat"),
        ("理想i8的内饰做工怎么样", "rag"),
        ("小米YU7的能耗表现如何", "rag"),
        ("蔚来的充换电网络建设到什么规模了", "rag"),
        ("华为在汽车领域有哪些新动作", "rag"),
        ("哪个车好", "clarify"),
        ("帮我看看这个车", "clarify"),
        ("它值得入手吗", "clarify"),
    ],
)
def test_classify_stable_common_routes_without_model(question, expected):
    from app import nlu

    with patch("app.nlu.chat") as mock_chat:
        result = nlu.classify(question)

    assert result["intent"] == expected
    assert result["llm_calls"] == 0
    mock_chat.assert_not_called()


def test_off_topic_rule_does_not_swallow_automotive_question():
    from app.nlu import deterministic_intent_hint

    assert deterministic_intent_hint("天气如何影响新能源汽车销量") is None


def test_classify_mixed_greeting_never_silently_becomes_chat():
    from app import nlu

    model = (
        '{"intent":"chat","confidence":0.95,"top2_intent":"clarify",'
        '"top2_confidence":0.02,"brands":[],"models":[],"time":[],'
        '"metrics":[],"energy_types":[],"normalized_question":"你好比亚迪"}'
    )
    with patch("app.nlu.chat", return_value=model):
        result = nlu.classify("你好比亚迪")

    assert result["intent"] == "clarify"
    assert result["source"] == "mixed_greeting_guard"
    assert result["entities"]["brands"] == ["比亚迪"]
    assert result["is_complete"] is False
    assert result["llm_calls"] == 1


def test_classify_merges_local_brand_into_partial_model_entities():
    from app import nlu

    model = (
        '{"intent":"rag","confidence":0.9,"top2_intent":"clarify",'
        '"top2_confidence":0.05,"brands":[],"models":[],"time":["2026年"],'
        '"metrics":[],"energy_types":[],"normalized_question":"比亚迪怎么样"}'
    )
    with patch("app.nlu.chat", return_value=model):
        result = nlu.classify("比亚迪怎么样")

    assert result["intent"] == "rag"
    assert result["entities"]["brands"] == ["比亚迪"]
    assert result["entities"]["time"] == ["2026年"]
    assert result["llm_calls"] == 1


def test_config_load_does_not_eagerly_load_few_shot_embeddings(monkeypatch):
    from app import nlu

    monkeypatch.setattr(nlu, "_cfg", None)
    monkeypatch.setattr(nlu, "_few_shot_initialized", False)
    with patch("app.nlu.embed_passages") as embed:
        assert nlu.layer1_prefilter("你好")["intent"] == "chat"
    embed.assert_not_called()
