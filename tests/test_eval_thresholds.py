"""评测阈值门禁（CI 阻断合并的关口）。

仓库必须提交四份完整评测报告；报告缺失、字段漂移或指标低于红线都应直接失败，
避免出现“CI 绿色，但关键 RAG 门禁其实被 skip”的假象。
"""
import json
import hashlib
import os
import re
import subprocess
from pathlib import Path, PureWindowsPath

import pytest

from eval.common import (
    TEXT_HASH_SEMANTICS,
    canonical_text_bytes,
    canonical_text_sha256,
    json_sha256,
    text_file_manifest,
    text_files_sha256,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "eval", "reports")
ROOT_PATH = Path(ROOT)

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
    ("name", "meta_path", "commit_path", "dirty_path"),
    [
        (
            "data_quality.json",
            ("_meta",),
            ("git_commit",),
            ("dirty_worktree",),
        ),
        (
            "intent.json",
            ("_meta",),
            ("git_commit",),
            ("dirty_worktree",),
        ),
        (
            "rag.json",
            ("_meta",),
            ("git", "commit"),
            ("git", "dirty"),
        ),
        (
            "text2sql.json",
            ("meta",),
            ("git_commit",),
            ("dirty_worktree",),
        ),
    ],
)
def test_report_provenance_gate(name, meta_path, commit_path, dirty_path):
    """提交报告必须来自干净工作树，并能定位代码与固定评测数据。"""
    meta = _val(_load(name), *meta_path)
    commit = _val(meta, *commit_path)
    dirty = _val(meta, *dirty_path)

    assert GIT_SHA_RE.fullmatch(commit), f"{name} git commit 非完整 SHA"
    assert dirty is False, f"{name} 来自 dirty worktree，不能作为可复现证据"
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert ancestor.returncode == 0, (
        f"{name} 记录的 commit {commit} 不是当前 HEAD 的祖先"
    )


@pytest.mark.parametrize(
    ("name", "meta_path", "dataset", "config_inputs"),
    [
        (
            "intent.json",
            ("_meta",),
            "eval/datasets/intent.jsonl",
            ("app/nlu.py", "config/nlu.yaml"),
        ),
        (
            "text2sql.json",
            ("meta",),
            "eval/datasets/text2sql.jsonl",
            ("app/text2sql.py", "config/nlu.yaml"),
        ),
    ],
)
def test_text_evaluation_input_hashes_are_current(
    name, meta_path, dataset, config_inputs
):
    """不能只检查“像 SHA”；必须由当前仓库输入实际重算。"""
    meta = _val(_load(name), *meta_path)
    dataset_path = ROOT_PATH / dataset
    config_paths = [ROOT_PATH / relative for relative in config_inputs]

    assert _val(meta, "hash_semantics") == TEXT_HASH_SEMANTICS
    assert _val(meta, "dataset_sha256") == canonical_text_sha256(dataset_path)
    assert _val(meta, "config_files") == text_file_manifest(
        config_paths,
        root=ROOT_PATH,
    )
    assert _val(meta, "config_sha256") == text_files_sha256(
        config_paths,
        root=ROOT_PATH,
    )


def test_rag_evaluation_input_hashes_are_current():
    """重算 RAG dataset、运行配置和完整 seed corpus manifest。"""
    from eval.rag_eval import _evaluation_config

    meta = _val(_load("rag.json"), "_meta")
    assert _val(meta, "hash_semantics") == TEXT_HASH_SEMANTICS
    assert _val(meta, "dataset_sha256") == canonical_text_sha256(
        ROOT_PATH / "eval/datasets/rag.jsonl"
    )

    evaluation_config = _evaluation_config()
    assert _val(meta, "evaluation_config") == evaluation_config
    assert _val(meta, "evaluation_config_sha256") == json_sha256(
        evaluation_config
    )

    seed_files = []
    for path in sorted((ROOT_PATH / "data/seed_kb").glob("*.md")):
        payload = canonical_text_bytes(path)
        seed_files.append({
            "filename": path.name,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    expected_manifest = {
        "file_count": len(seed_files),
        "hash_semantics": TEXT_HASH_SEMANTICS,
        "sha256": json_sha256(seed_files),
        "files": seed_files,
    }
    assert _val(meta, "seed_corpus_manifest") == expected_manifest


def test_rag_report_does_not_leak_machine_model_paths():
    meta = _val(_load("rag.json"), "_meta")
    for section in ("embedding", "reranker"):
        model_name = _val(meta, section, "model_name")
        assert not os.path.isabs(model_name)
        assert not PureWindowsPath(model_name).is_absolute()
        assert "\\" not in model_name


def _git_tracked(relative: str) -> bool:
    return subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).returncode == 0


def test_data_quality_report_discloses_local_snapshot_boundary():
    """未提交的 DB/raw 只能证明本地快照，不能伪装 fresh-clone 可复现。"""
    meta = _val(_load("data_quality.json"), "_meta")
    assert _val(meta, "source_scope") == "local_snapshot"
    assert _val(meta, "hash_semantics") == TEXT_HASH_SEMANTICS

    expected = {
        "database": ("bi_demo.db", False),
        "raw_sales": ("data/raw/sales_rank_raw.jsonl", True),
    }
    inputs = _val(meta, "snapshot_inputs")
    tracked_states = []
    for name, (relative, is_text) in expected.items():
        item = _val(inputs, name)
        tracked = _git_tracked(relative)
        tracked_states.append(tracked)
        assert _val(item, "path") == relative
        assert _val(item, "tracked") is tracked
        recorded_hash = _val(item, "sha256")
        assert SHA256_RE.fullmatch(recorded_hash)

        path = ROOT_PATH / relative
        if tracked:
            assert path.exists(), f"tracked snapshot input missing: {relative}"
            expected_hash = (
                canonical_text_sha256(path)
                if is_text
                else hashlib.sha256(path.read_bytes()).hexdigest()
            )
            assert recorded_hash == expected_hash

    repository_reproducible = all(tracked_states)
    assert _val(meta, "repository_reproducible") is repository_reproducible
    if not repository_reproducible:
        disclosure = _val(meta, "source_disclosure").lower()
        assert "local data snapshot" in disclosure
        assert "fresh clone cannot independently recompute" in disclosure
