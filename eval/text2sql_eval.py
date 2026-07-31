"""Text2SQL 执行准确率评测：项目 Text2SQL 生成 SQL → 执行 → 与标准 SQL 结果集等价比对。
拆「首次执行」与「带自校验重试」两口径，量化重试增益。

用法：
  python eval/text2sql_eval.py --check-gold   # 只校验 60 条标准SQL 都能执行且非空（快，无 LLM）
  python eval/text2sql_eval.py --limit 6      # 小样本真跑（含 LLM）
  python eval/text2sql_eval.py                # 全量
产出：eval/reports/text2sql.json + .md
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from eval.common import load_jsonl, result_set_equal, pct  # noqa: E402
from app.text2sql import (  # noqa: E402
    SYS,
    DOMAIN,
    FEWSHOT,
    _brand_entity_hint,
    _extract_sql,
)
from app.schema_linking import link_schema                  # noqa: E402
from app.sql_guard import ensure_safe, with_limit, UnsafeSQLError  # noqa: E402
from app.db import run_query                                # noqa: E402
from app.llm import chat                                    # noqa: E402
from app.config import MAX_SQL_RETRY                        # noqa: E402
from app.graph import _validate_sql_shape                   # noqa: E402

DATASET = os.path.join(ROOT, "eval", "datasets", "text2sql.jsonl")
REPORT_DIR = os.path.join(ROOT, "eval", "reports")


def _exec(sql):
    safe = with_limit(ensure_safe(sql))
    return run_query(safe), safe


def gen_and_run(question, max_retry):
    """生成 SQL 并执行；执行报错则回喂修正重试。返回 (first_result, final_result)。
    result = {sql, rows, attempts, exec_ok, error}。first=第一次，final=执行成功或耗尽。"""
    schema = link_schema(question)
    msgs = [{"role": "system", "content": SYS},
            {"role": "user", "content": (
                f"{DOMAIN}\n\n{_brand_entity_hint(question)}{FEWSHOT}\n"
                f"可用表结构:\n{schema}\n\nQ: {question}\nSQL:"
            )}]
    first = None
    res = None
    for attempt in range(max_retry + 1):
        sql = _extract_sql(chat(msgs, temperature=0.0))
        try:
            (cols, rows), safe = _exec(sql)
            shape_ok, shape_reason = _validate_sql_shape(
                question, safe, cols, rows
            )
            res = {
                "sql": safe,
                "rows": rows,
                "attempts": attempt + 1,
                "exec_ok": shape_ok,
                "error": None if shape_ok else f"语义结构不匹配：{shape_reason}",
            }
        except (UnsafeSQLError, Exception) as e:  # noqa: BLE001
            res = {"sql": sql, "rows": [], "attempts": attempt + 1, "exec_ok": False, "error": str(e)[:160]}
        if attempt == 0:
            first = res
        if res["exec_ok"]:
            return first, res
        msgs.append({"role": "assistant", "content": res["sql"]})
        msgs.append({"role": "user", "content": f"上面的 SQL 执行或语义校验未通过：{res['error']}\n请修正后只输出一条 SELECT。"})
    return first, res


def check_gold():
    data = load_jsonl(DATASET)
    bad = []
    for it in data:
        try:
            cols, rows = run_query(with_limit(ensure_safe(it["gold_sql"])))
            if not rows:
                bad.append((it["id"], "EMPTY"))
        except Exception as e:  # noqa: BLE001
            bad.append((it["id"], str(e)[:80]))
    print(f"标准SQL 自检：{len(data)} 条，问题 {len(bad)} 条")
    for b in bad:
        print("  ", b)
    return bad


def run(limit=None, max_retry=MAX_SQL_RETRY):
    data = load_jsonl(DATASET)
    if limit:
        data = data[:limit]
    n = len(data)
    rows_out = []
    first_correct = final_correct = 0
    for i, it in enumerate(data, 1):
        gold_rows = run_query(with_limit(ensure_safe(it["gold_sql"])))[1]
        if not gold_rows:
            raise RuntimeError(
                f"{it['id']} gold SQL returned no rows; fix the dataset before scoring"
            )
        ordered = bool(it.get("ordered"))
        first, final = gen_and_run(it["q"], max_retry)
        fm = first["exec_ok"] and result_set_equal(gold_rows, first["rows"], ordered)
        lm = final["exec_ok"] and result_set_equal(gold_rows, final["rows"], ordered)
        first_correct += fm
        final_correct += lm
        rows_out.append({"id": it["id"], "q": it["q"], "first_match": fm, "final_match": lm,
                         "attempts": final["attempts"], "exec_ok": final["exec_ok"],
                         "pred_sql": final["sql"], "error": final["error"]})
        print(f"   [{i}/{n}] {it['id']} first={'Y' if fm else 'n'} final={'Y' if lm else 'n'} att={final['attempts']}")
    res = {"n": n, "max_retry": max_retry,
           "first_pass_accuracy": round(first_correct / n, 4) if n else 0,
           "exec_accuracy": round(final_correct / n, 4) if n else 0,
           "retry_gain": round((final_correct - first_correct) / n, 4) if n else 0,
           "first_correct": first_correct, "final_correct": final_correct,
           "meta": _build_meta(),
           "rows": rows_out}
    return res


def _build_meta() -> dict:
    """Evaluation metadata for reproducibility."""
    meta = {"timestamp": datetime.now(timezone.utc).isoformat()}
    try:
        meta["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, cwd=ROOT).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], text=True, cwd=ROOT).strip()
        meta["dirty_worktree"] = bool(dirty)
    except Exception:
        pass
    try:
        with open(DATASET, "rb") as f:
            meta["dataset_sha256"] = hashlib.sha256(f.read()).hexdigest()
    except Exception:
        pass
    meta["model"] = os.environ.get("LLM_MODEL", "unknown")
    meta["provider"] = os.environ.get("LLM_PROVIDER", "unknown")
    try:
        import hashlib as _h
        config_files = [os.path.join(ROOT, "app", "text2sql.py"),
                        os.path.join(ROOT, "config", "nlu.yaml")]
        h = _h.sha256()
        for cf in config_files:
            if os.path.exists(cf):
                with open(cf, "rb") as _f:
                    h.update(_f.read())
        meta["config_sha256"] = h.hexdigest()
    except Exception:
        pass
    try:
        from app.db import run_query
        _, rows = run_query("SELECT COUNT(*) c FROM fact_sales_rank")
        meta["fact_rows"] = rows[0]["c"] if rows else 0
    except Exception:
        pass
    return meta


def to_markdown(r):
    L = ["# Text2SQL 执行准确率评测报告", "",
         f"- 样本数：**{r['n']}**，最大重试：{r['max_retry']}",
         f"- **执行准确率(EX，带自校验重试)：{pct(r['final_correct'], r['n'])}**（{r['final_correct']}/{r['n']}）",
         f"- 首次执行准确率(不重试)：{pct(r['first_correct'], r['n'])}（{r['first_correct']}/{r['n']}）",
         f"- **自校验重试增益：+{r['retry_gain'] * 100:.1f} 个百分点**",
         "", "## 错误/失败案例", "", "| id | att | 问题 | 预测SQL/报错 |", "|---|---|---|---|"]
    for x in r["rows"]:
        if not x["final_match"]:
            detail = x["error"] or (x["pred_sql"] or "")[:120].replace("\n", " ")
            L.append(f"| {x['id']} | {x['attempts']} | {x['q']} | {detail} |")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--check-gold", action="store_true")
    ap.add_argument("--max-retry", type=int, default=MAX_SQL_RETRY)
    args = ap.parse_args()
    if args.check_gold:
        bad = check_gold()
        raise SystemExit(1 if bad else 0)
    print(f"== Text2SQL 评测（limit={args.limit or '全量'}, max_retry={args.max_retry}）==")
    r = run(args.limit, args.max_retry)
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(REPORT_DIR, "text2sql.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    with open(os.path.join(REPORT_DIR, "text2sql.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(r))
    print(f"\nEX(带重试)={pct(r['final_correct'], r['n'])}  首次={pct(r['first_correct'], r['n'])}  "
          f"重试增益=+{r['retry_gain'] * 100:.1f}pp")
    print(f"报告 → {REPORT_DIR}/text2sql.md")


if __name__ == "__main__":
    main()
