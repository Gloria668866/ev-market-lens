"""RAG（RAGAS 口径）评测：四指标 + 防幻觉率 + 多源冲突处理率 + 检索消融。

指标（按 RAGAS 原定义，judge 用项目 DeepSeek；检索命中率为确定性计算）：
- context_precision / context_recall / faithfulness / answer_relevancy  → eval/common.py
- 防幻觉率(none 类)：库里没有的问题应 has_answer=false
- 冲突处理率(conflict 类)：答案同时并列两个口径值、不取平均
- 消融：纯向量召回 / 混合召回(RRF) / 混合+rerank 的检索命中率(hit-recall)对比 → 量化「父子分块+rerank 增益」

用法：
  python eval/rag_eval.py --ids rag-001,rag-027,rag-043,rag-049   # 小样本验证（覆盖四类）
  python eval/rag_eval.py --limit 10
  python eval/rag_eval.py                                          # 全量
产出：eval/reports/rag.json + .md
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from eval.common import (load_jsonl, pct, context_precision, context_recall,
                         faithfulness, answer_relevancy)  # noqa: E402
from app.rag import retrieve as R, pg, embed, ingest       # noqa: E402
from app.config import RERANK_SCORE_MIN, RERANK_TOP_K      # noqa: E402

DATASET = os.path.join(ROOT, "eval", "datasets", "rag.jsonl")
REPORT_DIR = os.path.join(ROOT, "eval", "reports")


def get_uid():
    with pg.conn() as c:
        return c.execute("select id from users where username='rag_demo'").fetchone()[0]


def ensure_user(name):
    with pg.conn() as c:
        c.execute("INSERT INTO users(username,password_hash) VALUES(%s,'x') ON CONFLICT(username) DO NOTHING", (name,))
        c.commit()
        return c.execute("select id from users where username=%s", (name,)).fetchone()[0]


def clear_user_docs(uid):
    with pg.conn() as c:
        ids = [r[0] for r in c.execute("select id from kb_document where user_id=%s and deleted_at is null", (uid,)).fetchall()]
    for d in ids:
        try:
            pg.soft_delete(d)
        except Exception:
            pass


# ---------------- 检索（带阈值闸，复刻 answer_question 流程但暴露 contexts） ----------------
def retrieve_blocks(uid, q):
    children = R.hybrid_recall(uid, q)
    if not children:
        return None, [], [], 0.0
    top, used = R.rerank(q, children)
    top_score = top[0]["score_final"] if top else 0.0
    if used and top_score < RERANK_SCORE_MIN:        # 防幻觉闸：最高分太低 → 判无依据
        return None, [], [], top_score
    blocks = R.merge_parents(top)
    return blocks, [b["content"] for b in blocks], [b["doc_id"] for b in blocks], top_score


def answer_with_ctx(uid, q):
    blocks, ctxs, dids, score = retrieve_blocks(uid, q)
    if blocks is None:
        return {"answer": R.NO_ANSWER, "citations": [], "has_answer": False}, ctxs, dids
    res = R.generate(q, blocks)
    return res, ctxs, dids


# ---------------- 消融：三种检索配置取 top-k 的命中 doc_ids ----------------
def cfg_vec(uid, q, k):
    hits = pg.search(uid, embed.embed_query(q), top_k=k)
    return [h["doc_id"] for h in hits[:k]]


def cfg_hybrid(uid, q, k):
    return [h["doc_id"] for h in R.hybrid_recall(uid, q)[:k]]


def cfg_rerank(uid, q, k):
    ch = R.hybrid_recall(uid, q)
    if not ch:
        return []
    top, _ = R.rerank(q, ch)
    return [h["doc_id"] for h in top[:k]]


def hit_recall(expected, retrieved):
    if not expected:
        return None
    exp = set(expected)
    return round(len(exp & set(retrieved)) / len(exp), 4)


def inject_conflict(uid, it):
    """注入冲突文档，返回 [doc_id]（用于 expected + 末尾软删）。"""
    ids = []
    for d in it.get("inject", []):
        ingest.ingest_bytes(uid, d["name"], d["text"].encode("utf-8"), "md", title=d["title"])
        with pg.conn() as c:
            row = c.execute("select id from kb_document where user_id=%s and filename=%s order by id desc limit 1",
                            (uid, d["name"])).fetchone()
        if row:
            ids.append(row[0])
    return ids


def run(limit=None, ids=None, ablation=True):
    uid = get_uid()
    data = load_jsonl(DATASET)
    if ids:
        want = set(ids.split(","))
        data = [d for d in data if d["id"] in want]
    elif limit:
        data = data[:limit]

    conf_uid = None
    rows = []
    try:
        for i, it in enumerate(data, 1):
            cat = it["category"]
            expected = it.get("expected_doc_ids", [])
            use_uid = uid
            if cat == "conflict":
                # 冲突类用隔离用户：库里只有注入的两篇，必能召回 → 纯测「并列两口径」逻辑，剔除大库召回变量
                if conf_uid is None:
                    conf_uid = ensure_user("eval_conflict")
                    clear_user_docs(conf_uid)
                expected = inject_conflict(conf_uid, it)
                use_uid = conf_uid

            res, ctxs, dids = answer_with_ctx(use_uid, it["question"])
            ans, has = res["answer"], res["has_answer"]
            rec = {"id": it["id"], "category": cat, "has_answer": has}

            if cat == "none":
                rec["correct"] = (has is False)          # 防幻觉：应拒答
            else:
                gt = it["ground_truth"]
                rec["hit_recall"] = hit_recall(expected, dids)
                rec["context_precision"] = context_precision(it["question"], gt, ctxs)
                rec["context_recall"] = context_recall(gt, ctxs)
                rec["faithfulness"] = faithfulness(ans, ctxs)
                rec["answer_relevancy"] = answer_relevancy(it["question"], ans)
                rec["answered"] = bool(has)
                if cat == "conflict":
                    vals = it.get("conflict_values", [])
                    rec["conflict_ok"] = bool(has and all(v in ans for v in vals))
                # 消融（只对有期望文档的 single/multi 做，库稳定）
                if ablation and cat in ("single", "multi") and expected:
                    rec["abl"] = {
                        "vec": hit_recall(expected, cfg_vec(uid, it["question"], RERANK_TOP_K)),
                        "hybrid": hit_recall(expected, cfg_hybrid(uid, it["question"], RERANK_TOP_K)),
                        "rerank": hit_recall(expected, cfg_rerank(uid, it["question"], RERANK_TOP_K)),
                    }
            rows.append(rec)
            print(f"   [{i}/{len(data)}] {it['id']}({cat}) "
                  + (f"has_answer={has}" if cat == "none" else
                     f"hit={rec.get('hit_recall')} faith={rec.get('faithfulness')} relv={rec.get('answer_relevancy')}"))
    finally:
        if conf_uid is not None:
            clear_user_docs(conf_uid)                    # 评完清空隔离用户，不留注入文档

    return summarize(rows)


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def summarize(rows):
    ans_rows = [r for r in rows if r["category"] in ("single", "multi", "conflict")]
    answered = [r for r in ans_rows if r.get("answered")]   # 实际给出答案的子集：质量指标在此算（RAGAS 对「生成答案」评估的口径）
    none_rows = [r for r in rows if r["category"] == "none"]
    conf_rows = [r for r in rows if r["category"] == "conflict"]
    abl_rows = [r for r in rows if "abl" in r]

    summary = {
        "n": len(rows),
        "by_category": {c: sum(1 for r in rows if r["category"] == c) for c in ("single", "multi", "conflict", "none")},
        "metrics_answerable": {
            "hit_recall": _avg([r.get("hit_recall") for r in ans_rows]),       # 检索召回（全可答题，含拒答=0）
            "answer_rate": _avg([1.0 if r.get("answered") else 0.0 for r in ans_rows]),
            "answered_n": len(answered),
            "context_precision": _avg([r.get("context_precision") for r in answered]),
            "context_recall": _avg([r.get("context_recall") for r in answered]),
            "faithfulness": _avg([r.get("faithfulness") for r in answered]),
            "answer_relevancy": _avg([r.get("answer_relevancy") for r in answered]),
        },
        "hallucination_guard": {
            "n": len(none_rows),
            "abstention_rate": _avg([1.0 if r["correct"] else 0.0 for r in none_rows]),
        },
        "conflict_handling": {
            "n": len(conf_rows),
            "handle_rate": _avg([1.0 if r.get("conflict_ok") else 0.0 for r in conf_rows]),
        },
        "ablation": {
            "n": len(abl_rows),
            "vec": _avg([r["abl"]["vec"] for r in abl_rows]),
            "hybrid": _avg([r["abl"]["hybrid"] for r in abl_rows]),
            "rerank": _avg([r["abl"]["rerank"] for r in abl_rows]),
        },
        "rows": rows,
    }
    return summary


def to_markdown(r):
    m = r["metrics_answerable"]
    a = r["ablation"]
    L = ["# RAG（RAGAS 口径）评测报告", "",
         f"- 样本数：**{r['n']}**　分类：{r['by_category']}", "",
         "## 一、可答题四指标（single+multi+conflict）", "",
         "| 指标 | 值 |", "|---|---|",
         f"| context precision | {m['context_precision']} |",
         f"| context recall | {m['context_recall']} |",
         f"| faithfulness（忠实度/防幻觉） | {m['faithfulness']} |",
         f"| answer relevancy（答案相关性） | {m['answer_relevancy']} |",
         f"| 检索命中率 hit-recall（确定性） | {m['hit_recall']} |",
         f"| 应答率 answer_rate | {m['answer_rate']} |",
         "", "## 二、防幻觉（none 类，库里没有应拒答）", "",
         f"- 拒答正确率 abstention_rate：**{r['hallucination_guard']['abstention_rate']}**（n={r['hallucination_guard']['n']}）",
         "", "## 三、多源冲突处理（conflict 类）", "",
         f"- 并列两口径正确率 handle_rate：**{r['conflict_handling']['handle_rate']}**（n={r['conflict_handling']['n']}）",
         "", "## 四、检索消融（hit-recall，量化父子分块+rerank 增益）", "",
         "| 配置 | hit-recall |", "|---|---|",
         f"| 纯向量召回 | {a['vec']} |",
         f"| 混合召回(向量+全文 RRF) | {a['hybrid']} |",
         f"| 混合召回 + rerank（完整系统） | {a['rerank']} |",
         f"（消融样本 n={a['n']}）"]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--ids", type=str, default=None)
    ap.add_argument("--no-ablation", action="store_true")
    args = ap.parse_args()
    print(f"== RAG 评测（{'ids=' + args.ids if args.ids else 'limit=' + str(args.limit or '全量')}）==")
    r = run(args.limit, args.ids, ablation=not args.no_ablation)
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(REPORT_DIR, "rag.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    with open(os.path.join(REPORT_DIR, "rag.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(r))
    m = r["metrics_answerable"]
    print(f"\n四指标: ctxP={m['context_precision']} ctxR={m['context_recall']} "
          f"faith={m['faithfulness']} relv={m['answer_relevancy']} hit={m['hit_recall']}")
    print(f"防幻觉拒答率={r['hallucination_guard']['abstention_rate']}  冲突处理率={r['conflict_handling']['handle_rate']}")
    print(f"消融 hit-recall: 向量={r['ablation']['vec']} 混合={r['ablation']['hybrid']} +rerank={r['ablation']['rerank']}")
    print(f"报告 → {REPORT_DIR}/rag.md")


if __name__ == "__main__":
    main()
