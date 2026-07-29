"""意图路由评测：跑 graph.intent_router，出混淆矩阵 + 准确率 + 各类 P/R/F1 + 错分案例。

用法：
  .venv/Scripts/python.exe eval/intent_eval.py            # 全量
  .venv/Scripts/python.exe eval/intent_eval.py --limit 12 # 小样本验证 pipeline
产出：eval/reports/intent.json（机读，供 CI 阈值断言）+ eval/reports/intent.md（人读）。
"""
import argparse
import collections
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from eval.common import load_jsonl, pct  # noqa: E402
from app.graph import intent_router       # noqa: E402

LABELS = ["sql", "rag", "hybrid", "chat", "clarify"]
DATASET = os.path.join(ROOT, "eval", "datasets", "intent.jsonl")
REPORT_DIR = os.path.join(ROOT, "eval", "reports")
NLU_CONFIG = os.path.join(ROOT, "config", "nlu.yaml")


def _build_meta() -> dict:
    with open(DATASET, "rb") as stream:
        dataset_sha256 = hashlib.sha256(stream.read()).hexdigest()
    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": os.environ.get("LLM_MODEL", "unknown"),
        "dataset_sha256": dataset_sha256,
    }
    try:
        meta["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
        meta["dirty_worktree"] = bool(subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            text=True,
        ).strip())
    except Exception:
        pass
    digest = hashlib.sha256()
    for relative in ("app/nlu.py", "config/nlu.yaml"):
        path = os.path.join(ROOT, relative)
        if os.path.exists(path):
            with open(path, "rb") as stream:
                digest.update(stream.read())
    meta["config_sha256"] = digest.hexdigest()
    return meta


def predict(q: str) -> dict:
    started = time.perf_counter()
    try:
        result = intent_router({"question": q})
        trace = (result.get("trace") or [{}])[0]
        return {
            "intent": result.get("intent", "error"),
            "source": trace.get("nlu_source") or trace.get("path") or "unknown",
            "llm_calls": trace.get("nlu_llm_calls"),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as e:  # noqa: BLE001
        print(f"   [warn] intent_router 失败: {str(e)[:80]}")
        return {
            "intent": "error",
            "source": "error",
            "llm_calls": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return round(
        ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower),
        2,
    )


def _few_shot_questions() -> set[str]:
    """Load runtime few-shot questions so the report can disclose exact overlap."""
    try:
        with open(NLU_CONFIG, encoding="utf-8") as stream:
            cfg = (yaml.safe_load(stream) or {}).get("nlu", {})
        return {
            item["question"].strip()
            for item in cfg.get("few_shot_examples", [])
            if item.get("question")
        }
    except Exception:
        return set()


def run(limit=None) -> dict:
    data = load_jsonl(DATASET)
    if limit:
        data = data[:limit]
    n = len(data)
    conf = collections.Counter()      # (gold, pred) -> count
    errors = []
    exact_few_shot = _few_shot_questions()
    outcomes = []
    path_counts = collections.Counter()
    llm_calls_total = 0
    latency_ms = []
    for i, it in enumerate(data, 1):
        prediction = predict(it["q"])
        pred = prediction["intent"]
        path_counts[prediction["source"]] += 1
        llm_calls_total += int(prediction["llm_calls"] or 0)
        latency_ms.append(prediction["latency_ms"])
        conf[(it["gold"], pred)] += 1
        outcomes.append({
            "correct": pred == it["gold"],
            "few_shot_exact_overlap": it["q"].strip() in exact_few_shot,
        })
        if pred != it["gold"]:
            errors.append({"id": it["id"], "q": it["q"], "gold": it["gold"], "pred": pred})
        if i % 10 == 0:
            print(f"   ...{i}/{n}")

    correct = sum(v for (g, p), v in conf.items() if g == p)
    accuracy = round(correct / n, 4) if n else 0.0
    overlap_count = sum(item["few_shot_exact_overlap"] for item in outcomes)
    non_overlap = [
        item for item in outcomes if not item["few_shot_exact_overlap"]
    ]
    non_overlap_correct = sum(item["correct"] for item in non_overlap)
    non_overlap_accuracy = (
        round(non_overlap_correct / len(non_overlap), 4) if non_overlap else 0.0
    )

    per_class = {}
    for lab in LABELS:
        tp = conf[(lab, lab)]
        fp = sum(conf[(g, lab)] for g in LABELS if g != lab)
        fn = sum(v for (g, p), v in conf.items() if g == lab and p != lab)
        support = sum(v for (g, p), v in conf.items() if g == lab)
        prec = round(tp / (tp + fp), 4) if tp + fp else 0.0
        rec = round(tp / (tp + fn), 4) if tp + fn else 0.0
        f1 = round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0
        per_class[lab] = {"tp": tp, "fp": fp, "fn": fn, "support": support,
                          "precision": prec, "recall": rec, "f1": f1}

    preds_seen = sorted({p for (_, p) in conf}, key=lambda x: (x not in LABELS, x))
    matrix = {g: {p: conf[(g, p)] for p in preds_seen} for g in LABELS}
    return {"n": n, "accuracy": accuracy, "correct": correct,
            "few_shot_exact_overlap_count": overlap_count,
            "non_exact_overlap_n": len(non_overlap),
            "non_exact_overlap_correct": non_overlap_correct,
            "non_exact_overlap_accuracy": non_overlap_accuracy,
            "path_counts": dict(sorted(path_counts.items())),
            "nlu_llm_calls_total": llm_calls_total,
            "zero_llm_route_rate": round(
                max(0, n - llm_calls_total) / n, 4
            ) if n else 0.0,
            "latency_ms": {
                "mean": round(statistics.fmean(latency_ms), 2) if latency_ms else 0.0,
                "p50": _percentile(latency_ms, 0.50),
                "p95": _percentile(latency_ms, 0.95),
                "max": round(max(latency_ms), 2) if latency_ms else 0.0,
            },
            "labels": LABELS, "pred_labels": preds_seen,
            "confusion": matrix, "per_class": per_class, "errors": errors}


def to_markdown(r: dict) -> str:
    L = ["# 意图路由评测报告", "",
         f"- 样本数：**{r['n']}**　整体准确率：**{pct(r['correct'], r['n'])}**（{r['correct']}/{r['n']}）",
         f"- 与运行时 few-shot 完全同文：**{r['few_shot_exact_overlap_count']}** 条",
         f"- 去掉完全同文样本后：**{pct(r['non_exact_overlap_correct'], r['non_exact_overlap_n'])}**"
         f"（{r['non_exact_overlap_correct']}/{r['non_exact_overlap_n']}）",
         f"- NLU 模型调用：**{r['nlu_llm_calls_total']} 次 / {r['n']} 题**；"
         f"零调用路由率 **{r['zero_llm_route_rate'] * 100:.1f}%**",
         f"- 端到端意图路由延迟：mean **{r['latency_ms']['mean']} ms**，"
         f"p50 **{r['latency_ms']['p50']} ms**，p95 **{r['latency_ms']['p95']} ms**",
         f"- 路径分布：`{json.dumps(r['path_counts'], ensure_ascii=False)}`",
         "- 边界：这仍是随规则与提示词共同维护的固定回归集，不是独立留出集或线上泛化准确率。",
         "", "## 混淆矩阵（行=真实 gold，列=预测 pred）", ""]
    preds = r["pred_labels"]
    L.append("| gold \\ pred | " + " | ".join(preds) + " | 合计 |")
    L.append("|" + "---|" * (len(preds) + 2))
    for g in r["labels"]:
        row = r["confusion"][g]
        tot = sum(row.values())
        L.append(f"| **{g}** | " + " | ".join(str(row.get(p, 0)) for p in preds) + f" | {tot} |")
    L += ["", "## 各类 Precision / Recall / F1", "",
          "| 意图 | support | precision | recall | f1 |", "|---|---|---|---|---|"]
    for lab in r["labels"]:
        c = r["per_class"][lab]
        L.append(f"| {lab} | {c['support']} | {c['precision']} | {c['recall']} | {c['f1']} |")
    L += ["", f"## 错分案例（{len(r['errors'])} 条）", ""]
    for e in r["errors"]:
        L.append(f"- `{e['id']}` 【{e['gold']}→{e['pred']}】{e['q']}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    print(f"== 意图路由评测（limit={args.limit or '全量'}）==")
    r = run(args.limit)
    r["_meta"] = _build_meta()
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(REPORT_DIR, "intent.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    with open(os.path.join(REPORT_DIR, "intent.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(r))
    print(f"\n整体准确率 {pct(r['correct'], r['n'])}（{r['correct']}/{r['n']}）")
    for lab in LABELS:
        c = r["per_class"][lab]
        print(f"  {lab:8s} P={c['precision']:.2f} R={c['recall']:.2f} F1={c['f1']:.2f} (n={c['support']})")
    print(f"报告 → {REPORT_DIR}/intent.md")


if __name__ == "__main__":
    main()
