"""RAG 关键路径单测：RRF 倒数排序融合 + LLM JSON 解析（纯逻辑，不连 PG/模型）。"""
import pytest

retrieve = pytest.importorskip("app.rag.retrieve")


def test_rrf_fuse_rewards_multi_list_hits():
    a = [{"chunk_id": 1}, {"chunk_id": 2}]
    b = [{"chunk_id": 2}, {"chunk_id": 3}]
    fused = retrieve._rrf_fuse(a, b)
    # chunk 2 在两路都命中 → 分数应最高
    assert fused[2] > fused[1] and fused[2] > fused[3]


def test_rrf_rank_matters():
    a = [{"chunk_id": 1}, {"chunk_id": 2}]   # 1 排前 → 分更高
    fused = retrieve._rrf_fuse(a)
    assert fused[1] > fused[2]


def test_parse_json_plain():
    assert retrieve._parse_json('{"answer":"x","used_sources":[1],"has_answer":true}')["has_answer"] is True


def test_parse_json_codeblock():
    r = retrieve._parse_json('```json\n{"answer":"y","used_sources":[],"has_answer":false}\n```')
    assert r["answer"] == "y"


def test_fallback_evidence_requires_two_recall_channels():
    top = [{"score_final": 0.032, "recall_sources": ["vector"]}]
    ok, reason = retrieve.evidence_is_sufficient(top, used_reranker=False)
    assert ok is False
    assert reason == "fallback_single_channel"


def test_fallback_evidence_accepts_strong_dual_channel_hit():
    top = [{"score_final": 0.032, "recall_sources": ["vector", "keyword"]}]
    ok, reason = retrieve.evidence_is_sufficient(top, used_reranker=False)
    assert ok is True, reason


def test_reranker_evidence_uses_absolute_threshold():
    ok, reason = retrieve.evidence_is_sufficient(
        [{"score_final": 0.1, "recall_sources": ["vector", "keyword"]}],
        used_reranker=True,
    )
    assert ok is False
    assert reason == "low_score"


def test_reranker_rejects_missing_ascii_model_anchor():
    ok, reason = retrieve.evidence_is_sufficient(
        [{
            "score_final": 0.9,
            "content": "奔驰品牌在新能源市场持续推出新产品。",
            "recall_sources": ["vector", "keyword"],
        }],
        used_reranker=True,
        question="奔驰EQS 2025年销量是多少？",
    )
    assert ok is False
    assert reason == "missing_query_anchor"
