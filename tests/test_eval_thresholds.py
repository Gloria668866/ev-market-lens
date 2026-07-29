"""评测阈值门禁（CI 阻断合并的关口）。

仓库必须提交四份完整评测报告；报告缺失、字段漂移或指标低于红线都应直接失败，
避免出现“CI 绿色，但关键 RAG 门禁其实被 skip”的假象。
"""
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "eval", "reports")

# 红线阈值（低于即阻断合并）
# 当前报告口径：意图准确率、Text2SQL 执行准确率、RAG 严格检索通过率、负例拒答率。
TH_INTENT_ACC = 0.95
TH_T2S_EX = 0.90
TH_RAG_STRICT = 0.95
TH_RAG_ABSTAIN = 0.95
TH_RAG_CLAIM_SOURCE = 0.95
TH_RAG_CLAIM_SUPPORT = 0.85
TH_RAG_CRITICAL_ANCHOR = 0.90
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _load(name):
    p = os.path.join(REPORTS, name)
    assert os.path.exists(p), f"{name} 未生成（先跑对应评测脚本并提交报告）"
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _val(d, *keys):
    """逐层取值；报告字段缺失是门禁配置漂移，必须失败。"""
    for k in keys:
        assert isinstance(d, dict) and d.get(k) is not None, (
            f"指标 {'/'.join(keys)} 缺失（评测报告结构已漂移，请更新报告或门禁）"
        )
        d = d[k]
    return d


def test_intent_accuracy_gate():
    report = _load("intent.json")
    assert _val(report, "n") >= 100
    assert _val(report, "accuracy") >= TH_INTENT_ACC


def test_text2sql_exec_accuracy_gate():
    report = _load("text2sql.json")
    assert _val(report, "n") >= 60
    assert _val(report, "exec_accuracy") >= TH_T2S_EX


def test_rag_strict_retrieval_gate():
    report = _load("rag.json")
    assert _val(report, "positive_count") >= 10
    assert _val(report, "negative_count") >= 5
    assert _val(report, "strict_pass_rate") >= TH_RAG_STRICT


def test_rag_hallucination_guard_gate():
    assert _val(_load("rag.json"), "abstain_rate") >= TH_RAG_ABSTAIN


def test_rag_claim_source_annotations_gate():
    assert (
        _val(_load("rag.json"), "claim_source_valid_rate")
        >= TH_RAG_CLAIM_SOURCE
    )


def test_rag_retrieved_claim_support_gate():
    assert (
        _val(_load("rag.json"), "retrieved_claim_support_rate")
        >= TH_RAG_CLAIM_SUPPORT
    )


def test_rag_critical_anchor_support_gate():
    assert (
        _val(_load("rag.json"), "critical_anchor_support_rate")
        >= TH_RAG_CRITICAL_ANCHOR
    )


def test_data_quality_report_gate():
    report = _load("data_quality.json")
    total = _val(report, "total")
    passed = _val(report, "passed")
    assert total >= 20
    assert passed == total


@pytest.mark.parametrize(
    ("name", "meta_path", "commit_path", "dirty_path", "hash_path"),
    [
        (
            "data_quality.json",
            ("_meta",),
            ("git_commit",),
            ("dirty_worktree",),
            ("raw_sha256",),
        ),
        (
            "intent.json",
            ("_meta",),
            ("git_commit",),
            ("dirty_worktree",),
            ("dataset_sha256",),
        ),
        (
            "rag.json",
            ("_meta",),
            ("git", "commit"),
            ("git", "dirty"),
            ("dataset_sha256",),
        ),
        (
            "text2sql.json",
            ("meta",),
            ("git_commit",),
            ("dirty_worktree",),
            ("dataset_sha256",),
        ),
    ],
)
def test_report_provenance_gate(
    name, meta_path, commit_path, dirty_path, hash_path
):
    """提交报告必须来自干净工作树，并能定位代码与固定评测数据。"""
    meta = _val(_load(name), *meta_path)
    commit = _val(meta, *commit_path)
    dirty = _val(meta, *dirty_path)
    dataset_hash = _val(meta, *hash_path)

    assert GIT_SHA_RE.fullmatch(commit), f"{name} git commit 非完整 SHA"
    assert dirty is False, f"{name} 来自 dirty worktree，不能作为可复现证据"
    assert SHA256_RE.fullmatch(dataset_hash), f"{name} 数据哈希无效"
