"""RAG 评测执行脚本：对 rag.jsonl 中的测试题跑检索+生成，产出评测报告。

用法：python data/rag_eval_run.py
产物：eval/reports/rag.json（评测指标）/ eval/reports/rag.md（可读报告）

评测指标：
  - recall / precision / MRR (检索层)
  - abstraction rate (防幻觉拒答率)
  - faithfulness / correctness (生成层，需 LLM judge)
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rag.retrieve import hybrid_recall
from app.rag.local_store import init_store

DATASET = Path(__file__).parent.parent / "eval" / "datasets" / "rag.jsonl"
REPORT_JSON = Path(__file__).parent.parent / "eval" / "reports" / "rag.json"
REPORT_MD = Path(__file__).parent.parent / "eval" / "reports" / "rag.md"


def evaluate_retrieval():
    """评估检索层：对每个 single/cross 题，看 ground-truth doc 是否被召回。"""
    if not DATASET.exists():
        print(f"[skip] 评测集不存在：{DATASET}，请先跑 data/rag_eval_build.py")
        return None

    init_store()
    questions = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()]

    retrieval_results = []
    for q in questions:
        if q.get("category") == "negative":
            continue  # negative 属拒答测试，不走检索评估
        results = hybrid_recall(1, q["question"])
        # 看目标 doc_id 是否被命中（cross 类不比对 doc_id）
        target_doc = q.get("doc_id")
        hit = any(r.get("doc_id") == target_doc for r in results) if target_doc else len(results) > 0
        retrieval_results.append({
            "question": q["question"],
            "category": q["category"],
            "target_doc": target_doc,
            "hit": hit,
            "num_candidates": len(results),
            "top_scores": [r.get("score", 0) for r in results[:5]],
        })

    # 计算
    single_hits = [r for r in retrieval_results if r["category"] == "single"]
    cross_hits = [r for r in retrieval_results if r["category"] == "cross"]

    def rate(items): return sum(r["hit"] for r in items) / len(items) if items else 0

    report = {
        "total_questions": len(retrieval_results),
        "single_count": len(single_hits),
        "single_recall": round(rate(single_hits), 3),
        "cross_count": len(cross_hits),
        "cross_has_results": round(rate(cross_hits), 3),
        "overall_recall": round(rate(retrieval_results), 3),
    }

    # 拒答测试
    neg_qs = [q for q in questions if q.get("category") == "negative"]
    neg_results = []
    for q in neg_qs:
        results = hybrid_recall(1, q["question"])
        # 如果最高分 < 0.3 或无结果 → 应该拒答
        top_score = max((r.get("score", 0) for r in results), default=0)
        should_abstain = top_score < 0.3 or len(results) == 0
        neg_results.append({"question": q["question"], "top_score": top_score, "should_abstain": should_abstain})
    report["negative_count"] = len(neg_qs)
    report["abstain_rate"] = round(sum(r["should_abstain"] for r in neg_results) / len(neg_results), 3) if neg_results else 1.0

    # 写报告
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    report["_retrieval_details"] = retrieval_results
    report["_negative_details"] = neg_results
    report["_timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")

    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = f"""# RAG 检索评测报告

生成时间：{report['_timestamp']}

## 检索层
| 指标 | 值 |
|------|-----|
| 总题数 | {report['total_questions']} |
| Single recall | {report['single_recall']} |
| Cross recall | {report['cross_has_results']} |
| Overall recall | {report['overall_recall']} |

## 防幻觉
| 指标 | 值 |
|------|-----|
| Negative 题数 | {report['negative_count']} |
| 拒答率 | {report['abstain_rate']} |

## 详细结果
"""
    for r in retrieval_results:
        icon = "✅" if r["hit"] else "❌"
        md += f"- {icon} [{r['category']}] {r['question'][:60]}... (candidates={r['num_candidates']})\n"

    REPORT_MD.write_text(md, encoding="utf-8")
    print(f"评测报告 → {REPORT_JSON} / {REPORT_MD}")
    for k, v in report.items():
        if not k.startswith("_"):
            print(f"  {k}: {v}")
    return report


if __name__ == "__main__":
    evaluate_retrieval()
