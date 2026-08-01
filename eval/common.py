"""评测公共工具：确定性 SQL 结果集等价比对与 JSONL/报表工具。

RAG 的当前公开评测实现位于 ``eval/rag_eval.py``。项目没有把自定义
LLM 打分函数冒充 RAGAS 指标；答案级能力边界以生成报告为准。
"""
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Iterable

TEXT_HASH_SEMANTICS = "sha256-lf-v1"
GENERATED_REPORT_PATHS = (
    "eval/reports/data_quality.json",
    "eval/reports/intent.json",
    "eval/reports/intent.md",
    "eval/reports/rag.json",
    "eval/reports/rag.md",
    "eval/reports/text2sql.json",
    "eval/reports/text2sql.md",
)


def canonical_text_bytes(path: str | Path) -> bytes:
    """Return text input bytes with checkout-specific newlines removed.

    Git may materialise tracked text as LF on Linux and CRLF on Windows.  Raw
    ``read_bytes()`` hashes therefore describe a checkout, not the committed
    evaluation input.  Evaluation datasets/configuration are UTF-8 text, so
    canonical LF bytes give both platforms the same digest while preserving
    every other byte.
    """
    payload = Path(path).read_bytes()
    return payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def canonical_text_sha256(path: str | Path) -> str:
    return hashlib.sha256(canonical_text_bytes(path)).hexdigest()


def json_sha256(value) -> str:
    """Hash a JSON-compatible value using a deterministic encoding."""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def text_file_manifest(
    paths: Iterable[str | Path],
    *,
    root: str | Path,
) -> list[dict]:
    """Build a stable manifest for an ordered set of repository text files."""
    root_path = Path(root).resolve()
    files = []
    for raw_path in paths:
        path = Path(raw_path).resolve()
        relative = path.relative_to(root_path).as_posix()
        payload = canonical_text_bytes(path)
        files.append({
            "path": relative,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    return sorted(files, key=lambda item: item["path"])


def text_files_sha256(
    paths: Iterable[str | Path],
    *,
    root: str | Path,
) -> str:
    """Hash file names plus canonical contents without concat ambiguity."""
    return json_sha256(text_file_manifest(paths, root=root))


def evaluation_git_snapshot(root: str | Path) -> dict:
    """Capture Git provenance while ignoring only generated reports.

    The documented sequential workflow rewrites tracked reports before the
    next evaluator starts.  Those known outputs must not make the next report
    self-declare as dirty.  Exact top-level excludes keep source, dataset,
    configuration, and unexpected files under ``eval/reports`` visible.
    """
    root_path = Path(root).resolve()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root_path,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if commit.returncode != 0:
        raise RuntimeError("cannot resolve evaluation Git commit")

    pathspecs = ["."] + [
        f":(top,exclude){relative}" for relative in GENERATED_REPORT_PATHS
    ]
    status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            *pathspecs,
        ],
        cwd=root_path,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if status.returncode != 0:
        raise RuntimeError("cannot inspect evaluation Git worktree")
    entries = [item for item in status.stdout.split("\0") if item]
    return {
        "commit": commit.stdout.strip(),
        "dirty": bool(entries),
        "dirty_path_count": len(entries),
    }

# ============================================================ SQL 结果集等价比对
def _canon(v):
    """单元格规范化：数字按 4 位小数比，其它去空白转字符串。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return f"{round(float(v), 4):.4f}"
    s = str(v).strip()
    try:
        return f"{round(float(s.replace(',', '')), 4):.4f}"
    except ValueError:
        return s


def _row_key(row_values):
    return tuple(_canon(v) for v in row_values)


def result_set_equal(gold_rows: list, pred_rows: list, ordered: bool = False) -> bool:
    """执行结果集等价（等价 SQL 算对）：默认无序多重集相等；ordered=True 时按行序比。
    gold_rows / pred_rows 为 dict 行列表（db.run_query 输出）。
    行数和列数必须一致；列名可不同但每行值的多重集必须匹配。"""
    if not gold_rows and not pred_rows:
        return True
    if not gold_rows or not pred_rows:
        return False
    if len(gold_rows) != len(pred_rows):
        return False
    if len(list(gold_rows[0].values())) != len(list(pred_rows[0].values())):
        return False

    g = [_row_key(r.values()) for r in gold_rows]
    p = [_row_key(r.values()) for r in pred_rows]
    if ordered:
        return g == p
    return Counter(g) == Counter(p)


# ============================================================ 报表小工具
def pct(x, n):
    return f"{(100.0 * x / n):.1f}%" if n else "—"


def load_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("//"):
                out.append(json.loads(line))
    return out
