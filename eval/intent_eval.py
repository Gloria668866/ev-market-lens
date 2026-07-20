"""意图路由评测：跑 graph.intent_router，出混淆矩阵 + 准确率 + 各类 P/R/F1 + 错分案例。

用法：
  .venv/Scripts/python.exe eval/intent_eval.py            # 全量
  .venv/Scripts/python.exe eval/intent_eval.py --limit 12 # 小样本验证 pipeline
产出：eval/reports/intent.json（机读，供 CI 阈值断言）+ eval/reports/intent.md（人读）。
"""
import argparse
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from eval.common import load_jsonl, pct  # noqa: E402
from app.graph import intent_router       # noqa: E402

LABELS = ["sql", "rag", "hybrid", "clarify"]
DATASET = os.path.join(ROOT, "eval", "datasets", "intent.jsonl")
REPORT_DIR = os.path.join(ROOT, "eval", "reports")


def predict(q: str) -> str:
    try:
        return intent_router({"question": q}).get("intent", "error")
    except Exception as e:  # noqa: BLE001
        print(f"   [warn] intent_router 失败: {str(e)[:80]}")
        return "error"


def run(limit=None) -> dict:
    data = load_jsonl(DATASET)
    if limit:
        data = data[:limit]
    n = len(data)
    conf = collections.Counter()      # (gold, pred) -> count
    errors = []
    for i, it in enumerate(data, 1):
        pred = predict(it["q"])
        conf[(it["gold"], pred)] += 1
        if pred != it["gold"]:
            errors.append({"id": it["id"], "q": it["q"], "gold": it["gold"], "pred": pred})
        if i % 10 == 0:
            print(f"   ...{i}/{n}")

    correct = sum(v for (g, p), v in conf.items() if g == p)
    accuracy = round(correct / n, 4) if n else 0.0

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
            "labels": LABELS, "pred_labels": preds_seen,
            "confusion": matrix, "per_class": per_class, "errors": errors}


def to_markdown(r: dict) -> str:
    L = ["# 意图路由评测报告", "",
         f"- 样本数：**{r['n']}**　整体准确率：**{pct(r['correct'], r['n'])}**（{r['correct']}/{r['n']}）",
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
