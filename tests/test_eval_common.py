"""评测公共工具单测。"""
import subprocess

from eval.common import (
    GENERATED_REPORT_PATHS,
    canonical_text_sha256,
    evaluation_git_snapshot,
    result_set_equal,
    text_files_sha256,
)


def test_equal_ignores_colname_and_roworder():
    gold = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    pred = [{"x": 3, "y": 4}, {"x": 1, "y": 2}]   # 列名不同、行序不同，但位置值相同
    assert result_set_equal(gold, pred)


def test_not_equal():
    assert not result_set_equal([{"a": 1}], [{"a": 2}])


def test_numeric_tolerance():
    assert result_set_equal([{"v": 1.0}], [{"v": "1.0000"}])


def test_ordered_flag():
    g = [{"a": 1}, {"a": 2}]
    p = [{"a": 2}, {"a": 1}]
    assert result_set_equal(g, p)                  # 默认无序 → 相等
    assert not result_set_equal(g, p, ordered=True)  # 有序 → 不等


def test_canonical_text_hash_is_stable_across_checkout_newlines(tmp_path):
    lf = tmp_path / "lf.jsonl"
    crlf = tmp_path / "crlf.jsonl"
    lf.write_bytes(b'{"id": 1}\n{"id": 2}\n')
    crlf.write_bytes(b'{"id": 1}\r\n{"id": 2}\r\n')

    assert canonical_text_sha256(lf) == canonical_text_sha256(crlf)


def _git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_sequential_evaluators_ignore_only_authoritative_report_outputs(tmp_path):
    _git(tmp_path, "init")
    source = tmp_path / "app" / "nlu.py"
    dataset = tmp_path / "eval" / "datasets" / "intent.jsonl"
    source.parent.mkdir(parents=True)
    dataset.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    dataset.write_text('{"id": 1}\n', encoding="utf-8")
    for relative in GENERATED_REPORT_PATHS:
        report = tmp_path / relative
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(
        tmp_path,
        "-c",
        "user.name=Codex Test",
        "-c",
        "user.email=codex@example.invalid",
        "commit",
        "-m",
        "fixture",
    )

    # Standard sequential runs rewrite earlier tracked reports.
    for relative in (
        "eval/reports/intent.json",
        "eval/reports/intent.md",
        "eval/reports/text2sql.json",
        "eval/reports/text2sql.md",
        "eval/reports/rag.json",
        "eval/reports/rag.md",
    ):
        (tmp_path / relative).write_text(
            f"generated {relative}\n",
            encoding="utf-8",
        )
        assert evaluation_git_snapshot(tmp_path)["dirty"] is False

    source.write_text("VALUE = 2\n", encoding="utf-8")
    assert evaluation_git_snapshot(tmp_path)["dirty"] is True

    _git(tmp_path, "checkout", "--", "app/nlu.py")
    unexpected = tmp_path / "eval" / "reports" / "manual-note.md"
    unexpected.write_text("not an evaluator output\n", encoding="utf-8")
    assert evaluation_git_snapshot(tmp_path)["dirty"] is True


def test_core_file_change_changes_implementation_hash(tmp_path):
    evaluator = tmp_path / "eval" / "intent_eval.py"
    core = tmp_path / "app" / "graph.py"
    evaluator.parent.mkdir(parents=True)
    core.parent.mkdir(parents=True)
    evaluator.write_text("def evaluate(): return route()\n", encoding="utf-8")
    core.write_text("def route(): return 'sql'\n", encoding="utf-8")
    inputs = (evaluator, core)

    before = text_files_sha256(inputs, root=tmp_path)
    core.write_text("def route(): return 'rag'\n", encoding="utf-8")
    after = text_files_sha256(inputs, root=tmp_path)

    assert after != before
