"""RAG 检索、证据覆盖与拒答的确定性回归评测。

这份评测不会调用答案生成模型，也不冒充 LLM-judge / RAGAS：

1. 对正例执行真实 ``hybrid_recall -> rerank -> evidence gate ->
   merge_parents``；
2. 先在 ``data/seed_kb`` 原文中校验人工 claims/evidence/critical anchors；
3. 再检查最终 merged context 是否按指定来源覆盖每条 claim 和关键锚点；
4. 对知识库未覆盖的问题检查证据门是否拒答。

运行前先执行 ``python data/build_local_kb.py``（本地）或
``python data/build_pg_kb.py``（生产 PG），保证检索库与种子语料一致。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app import config as app_config  # noqa: E402
from app.rag import retrieve as retrieval  # noqa: E402

DATASET = ROOT / "eval" / "datasets" / "rag.jsonl"
SEED_DIR = ROOT / "data" / "seed_kb"
REPORT_DIR = ROOT / "eval" / "reports"

_RETRIEVAL_CONFIG_KEYS = (
    "RECALL_VEC_K",
    "RECALL_KW_K",
    "RRF_K",
    "RRF_FALLBACK_SCORE_MIN",
    "RERANK_TOP_K",
    "RERANK_SCORE_MIN",
    "CONTEXT_TOKEN_BUDGET",
    "MAX_PARENTS",
)


def _rate(numerator: int | float, denominator: int) -> float:
    return round(float(numerator) / denominator, 4) if denominator else 0.0


def _normalise(text: Any) -> str:
    """Normalise only representation noise; keep numbers and punctuation.

    The evaluator deliberately does not perform fuzzy semantic matching. A wrong
    number or a missing qualifier must not pass because it "looks similar".
    """
    value = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(value.split()).lower()


def _contains(haystack: str, needle: str) -> bool:
    return bool(needle) and _normalise(needle) in _normalise(haystack)


def _as_nonempty_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _load_dataset() -> list[dict]:
    rows: list[dict] = []
    for line_number, line in enumerate(
        DATASET.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{DATASET} 第 {line_number} 行不是合法 JSON") from exc
        category = row.get("category")
        if category not in {"single", "cross", "negative"}:
            raise ValueError(
                f"{DATASET} 第 {line_number} 行 category={category!r} 不受支持"
            )
        if category != "negative":
            claims = row.get("claims")
            if not isinstance(claims, list) or not claims:
                raise ValueError(
                    f"{DATASET} 第 {line_number} 行正例必须包含人工核验 claims"
                )
            for claim in claims:
                required = ("id", "claim", "source_filename")
                if not isinstance(claim, dict) or any(
                    not str(claim.get(key) or "").strip() for key in required
                ):
                    raise ValueError(
                        f"{DATASET} 第 {line_number} 行 claim 缺 id/claim/source_filename"
                    )
                if not _as_nonempty_strings(claim.get("evidence")):
                    raise ValueError(
                        f"{DATASET} 第 {line_number} 行 claim 必须有 evidence"
                    )
                if not _as_nonempty_strings(claim.get("critical_anchors")):
                    raise ValueError(
                        f"{DATASET} 第 {line_number} 行 claim 必须有 critical_anchors"
                    )
        rows.append(row)
    return rows


def _expected_filenames(item: dict) -> list[str]:
    if item.get("expected_filenames") is not None:
        return list(item["expected_filenames"])
    if item.get("expected_filename"):
        return [item["expected_filename"]]
    return []


def _load_seed_sources() -> dict[str, str]:
    if not SEED_DIR.is_dir():
        raise RuntimeError(f"种子语料目录不存在：{SEED_DIR}")
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(SEED_DIR.glob("*.md"))
    }
    if not sources:
        raise RuntimeError(f"种子语料为空：{SEED_DIR}")
    return sources


def _seed_manifest() -> dict:
    files = []
    for path in sorted(SEED_DIR.glob("*.md")):
        payload = path.read_bytes()
        files.append({
            "filename": path.name,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    encoded = json.dumps(
        files,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "file_count": len(files),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "files": files,
    }


def _active_documents(user_id: int) -> dict[str, int]:
    docs = retrieval.store.list_documents(user_id)
    by_filename = {
        str(doc.get("filename")): int(doc["id"])
        for doc in docs
        if doc.get("filename") and doc.get("id") is not None
    }
    if not by_filename:
        backend_hint = (
            "python data/build_local_kb.py"
            if app_config.RAG_BACKEND == "local"
            else "python data/build_pg_kb.py"
        )
        raise RuntimeError(
            f"RAG_BACKEND={app_config.RAG_BACKEND!r} 没有可检索文档；"
            f"请先运行 {backend_hint}"
        )
    return by_filename


def _retrieve(question: str, user_id: int) -> dict:
    children = retrieval.hybrid_recall(user_id, question)
    top, reranker_used = retrieval.rerank(question, children)
    evidence_ok, evidence_reason = retrieval.evidence_is_sufficient(
        top,
        reranker_used,
        question,
    )
    # 即使证据门拒绝，也执行父块归并，以便报告可审计实际候选上下文。
    blocks = retrieval.merge_parents(top)
    return {
        "children": children,
        "top": top,
        "blocks": blocks,
        "reranker_used": reranker_used,
        "evidence_ok": evidence_ok,
        "evidence_reason": evidence_reason,
    }


def evaluate_claim_evidence(
    item: dict,
    seed_sources: dict[str, str],
    blocks: list[dict],
) -> dict:
    """Pure, source-aware evidence scorer used by runtime evaluation and tests.

    Evidence from another document never supports a claim, even when the same
    sentence or anchor happens to occur there.
    """
    expected_sources = set(_expected_filenames(item))
    contexts_by_source: dict[str, list[str]] = {}
    for block in blocks:
        filename = str(block.get("filename") or "")
        if filename:
            contexts_by_source.setdefault(filename, []).append(
                str(block.get("content") or "")
            )

    answer = str(item.get("answer") or "")
    details = []
    total_anchors = 0
    supported_anchors = 0
    answer_anchors = 0

    for claim in item.get("claims") or []:
        source = str(claim.get("source_filename") or "")
        evidence = _as_nonempty_strings(claim.get("evidence"))
        anchors = _as_nonempty_strings(claim.get("critical_anchors"))
        source_text = seed_sources.get(source, "")
        source_expected = source in expected_sources
        evidence_in_source = [
            _contains(source_text, snippet) for snippet in evidence
        ]
        anchors_in_evidence = [
            _contains("\n".join(evidence), anchor) for anchor in anchors
        ]
        source_valid = (
            bool(str(claim.get("claim") or "").strip())
            and bool(source_text)
            and source_expected
            and bool(evidence)
            and all(evidence_in_source)
            and bool(anchors)
            and all(anchors_in_evidence)
        )

        source_context = "\n".join(contexts_by_source.get(source, []))
        evidence_in_context = [
            _contains(source_context, snippet) for snippet in evidence
        ]
        anchor_in_context = [
            _contains(source_context, anchor) for anchor in anchors
        ]
        anchor_in_answer = [_contains(answer, anchor) for anchor in anchors]
        retrieved_support = (
            source_valid
            and bool(source_context)
            and all(evidence_in_context)
        )

        total_anchors += len(anchors)
        supported_anchors += sum(anchor_in_context)
        answer_anchors += sum(anchor_in_answer)
        details.append({
            "id": claim.get("id"),
            "claim": claim.get("claim"),
            "source_filename": source,
            "source_expected": source_expected,
            "source_exists": bool(source_text),
            "evidence_in_source": evidence_in_source,
            "anchors_in_evidence": anchors_in_evidence,
            "source_valid": source_valid,
            "source_in_merged_context": bool(source_context),
            "evidence_in_merged_context": evidence_in_context,
            "retrieved_support": retrieved_support,
            "critical_anchors": anchors,
            "critical_anchors_in_merged_context": anchor_in_context,
            "critical_anchors_in_answer": anchor_in_answer,
        })

    total_claims = len(details)
    valid_claims = sum(bool(row["source_valid"]) for row in details)
    supported_claims = sum(bool(row["retrieved_support"]) for row in details)
    return {
        "claim_count": total_claims,
        "claim_source_valid_count": valid_claims,
        "claim_source_valid_rate": _rate(valid_claims, total_claims),
        "retrieved_claim_support_count": supported_claims,
        "retrieved_claim_support_rate": _rate(supported_claims, total_claims),
        "critical_anchor_count": total_anchors,
        "critical_anchor_supported_count": supported_anchors,
        "critical_anchor_support_rate": _rate(supported_anchors, total_anchors),
        "answer_anchor_supported_count": answer_anchors,
        "answer_anchor_support_rate": _rate(answer_anchors, total_anchors),
        "claim_details": details,
    }


def _git_snapshot() -> dict:
    def _git(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""

    status_lines = [
        line for line in _git("status", "--porcelain").splitlines() if line
    ]
    return {
        "commit": _git("rev-parse", "HEAD") or "unknown",
        "dirty": bool(status_lines),
        "dirty_path_count": len(status_lines),
    }


def _runtime_state(value: Any) -> str:
    if value == "unloaded":
        return "unloaded"
    if value is None:
        return "unavailable"
    return f"loaded:{value.__class__.__name__}"


def _evaluation_meta(
    *,
    user_id: int,
    reranker_flags: list[bool],
) -> dict:
    retrieval_config = {
        key: getattr(app_config, key) for key in _RETRIEVAL_CONFIG_KEYS
    }
    evaluation_config = {
        "backend": app_config.RAG_BACKEND,
        "embedding": {
            "model_name": app_config.EMBED_MODEL_NAME,
            "model_version": app_config.EMBED_MODEL_VERSION,
            "dimension": app_config.EMBED_DIM,
            "max_tokens": app_config.EMBED_MAX_TOKENS,
        },
        "reranker": {"model_name": app_config.RERANK_MODEL_NAME},
        "retrieval": retrieval_config,
    }
    config_payload = json.dumps(
        evaluation_config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    local = app_config.RAG_BACKEND == "local"
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git": _git_snapshot(),
        "backend": app_config.RAG_BACKEND,
        "backend_disclosure": (
            "local SQLite + NumPy evaluation backend; this is not the production "
            "PostgreSQL/pgvector backend"
            if local
            else "PostgreSQL/pgvector evaluation backend"
        ),
        "user_id": user_id,
        "pipeline": [
            "hybrid_recall",
            "rerank",
            "evidence_is_sufficient",
            "merge_parents",
        ],
        "embedding": {
            "model_name": app_config.EMBED_MODEL_NAME,
            "model_version": app_config.EMBED_MODEL_VERSION,
            "dimension": app_config.EMBED_DIM,
            "max_tokens": app_config.EMBED_MAX_TOKENS,
            "runtime": _runtime_state(retrieval.embed._model),
        },
        "reranker": {
            "model_name": app_config.RERANK_MODEL_NAME,
            "runtime": _runtime_state(retrieval.embed._reranker),
            "used_for_all_questions": bool(reranker_flags)
            and all(reranker_flags),
        },
        "retrieval_config": retrieval_config,
        "evaluation_config_sha256": hashlib.sha256(config_payload).hexdigest(),
        "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        "seed_corpus_manifest": _seed_manifest(),
        "scope": "retrieval_evidence_coverage_and_abstention_only",
        "does_not_measure": [
            "generated_answer_faithfulness",
            "generated_answer_correctness",
            "citation_precision",
        ],
    }


def run(
    *,
    user_id: int = 0,
    limit: int | None = None,
    ids: set[str] | None = None,
) -> dict:
    data = _load_dataset()
    if ids:
        data = [item for item in data if item.get("id") in ids]
    if limit is not None:
        data = data[:limit]

    docs_by_filename = _active_documents(user_id)
    seed_sources = _load_seed_sources()
    positives: list[dict] = []
    negatives: list[dict] = []
    reranker_flags: list[bool] = []

    for index, item in enumerate(data, 1):
        result = _retrieve(item["question"], user_id)
        top = result["top"]
        blocks = result["blocks"]
        reranker_flags.append(bool(result["reranker_used"]))
        top_doc_ids = {
            int(hit["doc_id"])
            for hit in top
            if hit.get("doc_id") is not None
        }
        merged_filenames = {
            str(block.get("filename"))
            for block in blocks
            if block.get("filename")
        }
        top_scores = [
            round(float(hit.get("score_final", 0.0)), 4)
            for hit in top[:5]
        ]

        if item["category"] == "negative":
            should_abstain = not result["evidence_ok"]
            negatives.append({
                "id": item.get("id"),
                "question": item["question"],
                "top_score": top_scores[0] if top_scores else 0.0,
                "should_abstain": should_abstain,
                "reason": result["evidence_reason"],
                "reranker": bool(result["reranker_used"]),
                "num_candidates": len(result["children"]),
                "merged_context_sources": sorted(merged_filenames),
            })
            print(
                f"  [{index}/{len(data)}] {item.get('id', '-')} negative "
                f"abstain={should_abstain} reason={result['evidence_reason'] or '-'}"
            )
            continue

        expected_names = _expected_filenames(item)
        expected_ids = [
            docs_by_filename[name]
            for name in expected_names
            if name in docs_by_filename
        ]
        hit_count = len(set(expected_ids) & top_doc_ids)
        hit_recall = _rate(hit_count, len(expected_ids))
        context_count = len(set(expected_names) & merged_filenames)
        context_recall = _rate(context_count, len(expected_names))
        expected_resolved = len(expected_ids)
        claims = evaluate_claim_evidence(item, seed_sources, blocks)
        strict_pass = (
            expected_resolved == len(expected_names)
            and hit_recall == 1.0
            and context_recall == 1.0
            and result["evidence_ok"]
            and claims["claim_source_valid_rate"] == 1.0
            and claims["retrieved_claim_support_rate"] == 1.0
            and claims["critical_anchor_support_rate"] == 1.0
            and claims["answer_anchor_support_rate"] == 1.0
        )
        positives.append({
            "id": item.get("id"),
            "question": item["question"],
            "category": item["category"],
            "expected_filenames": expected_names,
            "expected_docs_resolved": expected_resolved,
            "hit_recall": hit_recall,
            "context_recall": context_recall,
            "evidence_ok": result["evidence_ok"],
            "evidence_reason": result["evidence_reason"],
            "strict_pass": strict_pass,
            "reranker": bool(result["reranker_used"]),
            "num_candidates": len(result["children"]),
            "num_merged_parents": len(blocks),
            "merged_context_sources": sorted(merged_filenames),
            "top_scores": top_scores,
            **claims,
        })
        print(
            f"  [{index}/{len(data)}] {item.get('id', '-')} {item['category']} "
            f"recall={hit_recall:.2f} context={context_recall:.2f} "
            f"claims={claims['retrieved_claim_support_rate']:.2f} "
            f"anchors={claims['critical_anchor_support_rate']:.2f} "
            f"strict={strict_pass}"
        )

    single = [row for row in positives if row["category"] == "single"]
    cross = [row for row in positives if row["category"] == "cross"]
    strict_passed = sum(1 for row in positives if row["strict_pass"])
    abstained = sum(1 for row in negatives if row["should_abstain"])
    claim_count = sum(row["claim_count"] for row in positives)
    valid_claims = sum(row["claim_source_valid_count"] for row in positives)
    supported_claims = sum(
        row["retrieved_claim_support_count"] for row in positives
    )
    anchor_count = sum(row["critical_anchor_count"] for row in positives)
    supported_anchors = sum(
        row["critical_anchor_supported_count"] for row in positives
    )
    answer_supported_anchors = sum(
        row["answer_anchor_supported_count"]
        for row in positives
    )

    def _mean(rows: list[dict], key: str) -> float:
        return _rate(sum(float(row[key]) for row in rows), len(rows))

    return {
        "total_questions": len(data),
        "positive_count": len(positives),
        "single_count": len(single),
        "single_recall": _mean(single, "hit_recall"),
        "cross_count": len(cross),
        "cross_recall": _mean(cross, "hit_recall"),
        "overall_recall": _mean(positives, "hit_recall"),
        "context_recall": _mean(positives, "context_recall"),
        "evidence_pass_rate": _mean(positives, "evidence_ok"),
        "claim_count": claim_count,
        "claim_source_valid_rate": _rate(valid_claims, claim_count),
        "retrieved_claim_support_rate": _rate(supported_claims, claim_count),
        "critical_anchor_count": anchor_count,
        "critical_anchor_support_rate": _rate(
            supported_anchors,
            anchor_count,
        ),
        "answer_anchor_support_rate": _rate(
            answer_supported_anchors,
            anchor_count,
        ),
        "strict_passed": strict_passed,
        "strict_pass_rate": _rate(strict_passed, len(positives)),
        "reranker_used": bool(reranker_flags) and all(reranker_flags),
        "negative_count": len(negatives),
        "abstain_rate": _rate(abstained, len(negatives)),
        "_retrieval_details": positives,
        "_negative_details": negatives,
        "_meta": _evaluation_meta(
            user_id=user_id,
            reranker_flags=reranker_flags,
        ),
    }


def to_markdown(report: dict) -> str:
    meta = report["_meta"]
    lines = [
        "# RAG 检索、证据覆盖与拒答回归报告",
        "",
        "> 执行真实 hybrid recall → rerank → evidence gate → parent merge，"
        "并确定性核对种子原文、merged context 与人工关键锚点。"
        "不代表生成答案的 faithfulness/correctness。",
        "",
        f"- 样本：**{report['total_questions']}**（正例 "
        f"{report['positive_count']}，负例 {report['negative_count']}）",
        f"- 严格正例通过率：**{report['strict_pass_rate']:.1%}**"
        f"（{report['strict_passed']}/{report['positive_count']}）",
        f"- 标注 claim 原文有效率：**{report['claim_source_valid_rate']:.1%}**",
        f"- merged context claim 覆盖率："
        f"**{report['retrieved_claim_support_rate']:.1%}**",
        f"- 关键锚点覆盖率：**{report['critical_anchor_support_rate']:.1%}**",
        f"- 负例拒答率：**{report['abstain_rate']:.1%}**",
        f"- reranker 全程启用：**{report['reranker_used']}**",
        f"- 后端披露：`{meta['backend_disclosure']}`",
        f"- Git：`{meta['git']['commit']}`，dirty={meta['git']['dirty']}",
        f"- 种子 manifest：`{meta['seed_corpus_manifest']['sha256']}`",
        "",
        "## 正例",
        "",
        "| id | 类别 | Top-K 召回 | 上下文召回 | claim 覆盖 | 锚点覆盖 | 严格通过 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["_retrieval_details"]:
        lines.append(
            f"| {row.get('id') or '-'} | {row['category']} | "
            f"{row['hit_recall']:.1%} | {row['context_recall']:.1%} | "
            f"{row['retrieved_claim_support_rate']:.1%} | "
            f"{row['critical_anchor_support_rate']:.1%} | "
            f"{row['strict_pass']} |"
        )
    lines.extend([
        "",
        "## 负例",
        "",
        "| id | 是否拒答 | 原因 |",
        "|---|---:|---|",
    ])
    for row in report["_negative_details"]:
        lines.append(
            f"| {row.get('id') or '-'} | {row['should_abstain']} | "
            f"{row['reason'] or '-'} |"
        )
    lines.extend([
        "",
        "## 口径边界",
        "",
        "- 本报告不调用最终答案生成模型。",
        "- `claim_source_valid_rate` 只检查人工 evidence/anchors 是否确实存在于"
        "其标注的原始种子文件。",
        "- `retrieved_claim_support_rate` 与 `critical_anchor_support_rate` "
        "按来源检查最终 merged context；无关文档中的相同文字不能代替目标来源。",
        "- 仍需单独建设生成答案 faithfulness、correctness 与 citation precision "
        "评测。",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 检索、证据覆盖与拒答评测")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", help="逗号分隔的数据集 id")
    parser.add_argument("--user-id", type=int, default=0)
    args = parser.parse_args()
    ids = {value.strip() for value in (args.ids or "").split(",") if value.strip()}

    print(
        f"== RAG 确定性证据覆盖评测（backend={app_config.RAG_BACKEND}, "
        f"limit={args.limit or '全量'}）=="
    )
    report = run(
        user_id=args.user_id,
        limit=args.limit,
        ids=ids or None,
    )
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "rag.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (REPORT_DIR / "rag.md").write_text(to_markdown(report), encoding="utf-8")

    print(
        f"\n严格正例 {report['strict_passed']}/{report['positive_count']}，"
        f"claim 原文有效率 {report['claim_source_valid_rate']:.1%}，"
        f"claim 覆盖率 {report['retrieved_claim_support_rate']:.1%}，"
        f"锚点覆盖率 {report['critical_anchor_support_rate']:.1%}，"
        f"负例拒答率 {report['abstain_rate']:.1%}"
    )
    print(f"报告 → {REPORT_DIR / 'rag.md'}")
    required_rates = []
    if report["positive_count"]:
        required_rates.extend([
            report["strict_pass_rate"],
            report["claim_source_valid_rate"],
            report["retrieved_claim_support_rate"],
            report["critical_anchor_support_rate"],
            report["answer_anchor_support_rate"],
        ])
    if report["negative_count"]:
        required_rates.append(report["abstain_rate"])
    if any(rate < 1.0 for rate in required_rates):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
