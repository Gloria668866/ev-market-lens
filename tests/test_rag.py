"""RAG 关键路径单测：RRF 倒数排序融合 + LLM JSON 解析（纯逻辑，不连 PG/模型）。"""
import concurrent.futures
import sys
import threading
import time
import types

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


def test_parse_json_rejects_wrong_source_types():
    result = retrieve._parse_json(
        '{"answer":"x","used_sources":["1"],"has_answer":true}',
    )
    assert result == {"answer": "", "used_sources": [], "has_answer": False}


def _generation_block(doc_id=7):
    return {
        "doc_id": doc_id,
        "page_no": 2,
        "chunk_id": 30,
        "hit_child_ids": [31],
        "heading_path": "市场规模",
        "title": "年度综述",
        "filename": "年度综述.md",
        "content": "预计突破 1300 万辆。",
    }


def test_generate_preserves_source_number_for_inline_citation(monkeypatch):
    monkeypatch.setattr(
        retrieve,
        "chat",
        lambda *_args, **_kwargs: (
            '{"answer":"预计突破1300万辆。[来源 1]",'
            '"used_sources":[1],"has_answer":true}'
        ),
    )
    result = retrieve.generate("销量多少", [_generation_block()])
    assert result["has_answer"] is True
    assert result["citations"][0]["source_no"] == 1
    assert result["citations"][0]["doc_id"] == 7


def test_generate_fails_closed_when_inline_source_does_not_match(monkeypatch):
    monkeypatch.setattr(
        retrieve,
        "chat",
        lambda *_args, **_kwargs: (
            '{"answer":"预计突破1300万辆。[来源 2]",'
            '"used_sources":[1],"has_answer":true}'
        ),
    )
    result = retrieve.generate("销量多少", [_generation_block()])
    assert result["has_answer"] is False
    assert result["citations"] == []
    assert result["answer"] == retrieve.NO_ANSWER


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


def test_reranker_is_loaded_once_under_concurrency(monkeypatch):
    from app.rag import embed

    created = 0
    created_lock = threading.Lock()

    class FakeCrossEncoder:
        def __init__(self, *_args, **_kwargs):
            nonlocal created
            with created_lock:
                created += 1
            time.sleep(0.05)

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(CrossEncoder=FakeCrossEncoder),
    )
    monkeypatch.setattr(embed, "_reranker", "unloaded")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        instances = list(executor.map(lambda _: embed._get_reranker(), range(8)))

    assert created == 1
    assert all(instance is instances[0] for instance in instances)


def test_local_reranker_never_probes_model_hub(monkeypatch, tmp_path):
    from app.rag import embed

    captured = {}

    class FakeCrossEncoder:
        def __init__(self, *_args, **kwargs):
            captured.update(kwargs)

    model_dir = tmp_path / "reranker"
    model_dir.mkdir()
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(CrossEncoder=FakeCrossEncoder),
    )
    monkeypatch.setattr(embed, "RERANK_MODEL_NAME", str(model_dir))
    monkeypatch.setattr(embed, "_reranker", "unloaded")

    embed._get_reranker()

    assert captured["local_files_only"] is True


def test_embedding_rejects_wrong_batch_size(monkeypatch):
    from app.rag import embed

    class FakeModel:
        def encode(self, *_args, **_kwargs):
            return []

    monkeypatch.setattr(embed, "get_model", lambda: FakeModel())
    with pytest.raises(RuntimeError, match="batch mismatch"):
        embed.embed_passages(["one passage"])


def test_embedding_rejects_wrong_dimension(monkeypatch):
    from app.rag import embed

    class FakeModel:
        def encode(self, *_args, **_kwargs):
            return [[0.0] * (embed.EMBED_DIM - 1)]

    monkeypatch.setattr(embed, "get_model", lambda: FakeModel())
    with pytest.raises(RuntimeError, match="shape"):
        embed.embed_passages(["one passage"])
