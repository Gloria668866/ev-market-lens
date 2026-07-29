"""Pure deterministic tests for source-aware RAG evidence scoring."""

from eval.rag_eval import (
    _load_dataset,
    _load_seed_sources,
    evaluate_claim_evidence,
)


def _item(*claims):
    return {
        "answer": "预计突破 1300 万辆。",
        "expected_filenames": ["年度综述.md", "技术路线.md"],
        "claims": list(claims),
    }


def _claim(source, evidence, anchors):
    return {
        "id": "c1",
        "claim": "测试 claim",
        "source_filename": source,
        "evidence": evidence,
        "critical_anchors": anchors,
    }


def _block(source, content):
    return {"filename": source, "content": content}


def test_wrong_number_is_not_valid_source_evidence():
    item = _item(_claim(
        "年度综述.md",
        ["全年销量预计突破 1400 万辆"],
        ["1400 万辆"],
    ))
    result = evaluate_claim_evidence(
        item,
        {"年度综述.md": "全年销量预计突破 1300 万辆。"},
        [_block("年度综述.md", "全年销量预计突破 1300 万辆。")],
    )

    assert result["claim_source_valid_rate"] == 0.0
    assert result["retrieved_claim_support_rate"] == 0.0


def test_cross_source_missing_claim_is_counted():
    first = _claim(
        "年度综述.md",
        ["全年销量预计突破 1300 万辆"],
        ["1300 万辆"],
    )
    second = {
        **_claim(
            "技术路线.md",
            ["发动机不直接驱动车轮"],
            ["不直接驱动车轮"],
        ),
        "id": "c2",
    }
    result = evaluate_claim_evidence(
        _item(first, second),
        {
            "年度综述.md": "全年销量预计突破 1300 万辆。",
            "技术路线.md": "发动机不直接驱动车轮。",
        },
        [_block("年度综述.md", "全年销量预计突破 1300 万辆。")],
    )

    assert result["claim_source_valid_rate"] == 1.0
    assert result["retrieved_claim_support_rate"] == 0.5
    assert result["critical_anchor_support_rate"] == 0.5


def test_unrelated_source_cannot_support_claim():
    claim = _claim(
        "年度综述.md",
        ["全年销量预计突破 1300 万辆"],
        ["1300 万辆"],
    )
    result = evaluate_claim_evidence(
        _item(claim),
        {
            "年度综述.md": "全年销量预计突破 1300 万辆。",
            "技术路线.md": "全年销量预计突破 1300 万辆。",
        },
        [_block("技术路线.md", "全年销量预计突破 1300 万辆。")],
    )

    assert result["claim_source_valid_rate"] == 1.0
    assert result["retrieved_claim_support_rate"] == 0.0
    assert result["critical_anchor_support_rate"] == 0.0


def test_all_positive_annotations_exist_in_original_seed_sources():
    """Dataset review cannot silently drift beyond the checked-in corpus."""
    seeds = _load_seed_sources()
    for item in _load_dataset():
        if item["category"] == "negative":
            continue
        # Full source documents make this an annotation-validity check only;
        # actual retrieval coverage is exercised by eval/rag_eval.py.
        blocks = [
            _block(filename, content)
            for filename, content in seeds.items()
        ]
        result = evaluate_claim_evidence(item, seeds, blocks)
        assert result["claim_source_valid_rate"] == 1.0, item["id"]
