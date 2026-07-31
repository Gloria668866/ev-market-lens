#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LangGraph 双脑编排 E2E 验收（PRD-2 §7 / DoD）。

验：1) 四种意图正确路由(sql/rag/hybrid/clarify)；2) hybrid 并行调双脑并合并；
    3) SQL 失败能重试、耗尽不塞错 SQL(降级)；4) 每步可在 trace 回溯。
前置：bi_demo.db 已建(数据脑) + rag_demo 知识库已建(知识脑)。
运行：HF_HUB_OFFLINE=1 PYTHONUTF8=1 .venv/Scripts/python.exe data/graph_demo.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.graph import run_agent, exec_sql, fix_sql, insight, route_exec
from app.rag import pg


def ok(c, m): print(f"  [{'PASS' if c else 'FAIL'}] {m}"); return c


def nodes(state):
    return [t["node"] for t in state.get("trace", [])]


def main():
    uid = pg.conn().execute("SELECT id FROM users WHERE username='rag_demo'").fetchone()[0]

    # ===== 1) 四种意图路由 =====
    print("=== 1) 四种意图正确路由 ===")
    s_sql = run_agent("2025年纯电销量前5的车系", uid)
    print(f"  sql:    intent={s_sql['intent']} nodes={nodes(s_sql)}")
    ok(s_sql["intent"] == "sql" and "exec_sql" in nodes(s_sql) and s_sql.get("chart"), "sql→schema_link→gen_sql→exec_sql→chart→insight")

    s_rag = run_agent("年度报告里对价格战是怎么解读的？", uid)
    print(f"  rag:    intent={s_rag['intent']} nodes={nodes(s_rag)} has_answer={s_rag.get('has_answer')}")
    ok(s_rag["intent"] == "rag" and "rag_retrieve" in nodes(s_rag), "rag→rag_retrieve→rag_answer")

    s_hyb = run_agent("比亚迪的销量趋势如何，行业怎么看？", uid)
    print(f"  hybrid: intent={s_hyb['intent']} nodes={nodes(s_hyb)}")
    ok(s_hyb["intent"] == "hybrid", "hybrid 识别")

    s_clr = run_agent("哪个车比较好啊", uid)
    print(f"  clarify:intent={s_clr['intent']} answer={s_clr.get('final_answer','')[:40]}")
    ok(s_clr["intent"] == "clarify" and "schema_link" not in nodes(s_clr), "clarify→反问→END(不走双脑)")

    # ===== 2) hybrid 并行调双脑并合并 =====
    print("\n=== 2) hybrid 并行双脑 + compose 合并 ===")
    ns = nodes(s_hyb)
    ok("schema_link" in ns and "rag_retrieve" in ns, "两个脑链都跑了(schema_link + rag_retrieve 都在 trace)")
    ok("compose" in ns, "compose 合并节点执行")
    fa = s_hyb.get("final_answer", "")
    print(f"  合并答案片段: {fa[:120]}")
    ok(len(fa) > 20, "产出合并后的统一答案")

    # ===== 3) SQL 失败重试 + 耗尽降级 =====
    print("\n=== 3) SQL 失败→重试环；耗尽→降级不塞错 SQL ===")
    # 路由逻辑：失败且可重试→fix_sql；耗尽→insight(降级)
    ok(route_exec({"sql_error": "boom", "retry_count": 0}) == "fix_sql", "失败且可重试 → fix_sql(进重试环)")
    from app.config import MAX_SQL_RETRY
    ok(route_exec({"sql_error": "boom", "retry_count": MAX_SQL_RETRY}) == "insight", "重试耗尽 → insight(降级)")
    ok(route_exec({"sql_error": None, "cols": [], "rows": []}) == "chart", "成功 → chart")
    # exec_sql 对坏 SQL 产出 sql_error（不抛崩）
    bad = exec_sql({"sql": "SELECT * FROM 不存在的表"})
    ok(bad.get("sql_error") is not None, "exec_sql 对坏 SQL 写 sql_error(不崩)")
    # 耗尽降级：insight 节点出降级话术，不含原始错误 SQL
    deg = insight({"question": "x", "sql_error": "no such table", "rows": []})
    ok(deg.get("degraded") and "SELECT" not in deg["insight"], "耗尽→友好降级话术(不把错 SQL 塞给用户)")

    # ===== 4) trace 可回溯 =====
    print("\n=== 4) 每步可在 trace 回溯 ===")
    print(f"  sql 链 trace: {[t['node'] for t in s_sql['trace']]}")
    print(f"  hybrid trace: {[t['node'] for t in s_hyb['trace']]}")
    ok(all("node" in t for t in s_sql["trace"]) and len(s_sql["trace"]) >= 4, "每步都有结构化 trace(节点+决策)")
    # trace 里能看到具体 SQL
    ok(any(t.get("sql") for t in s_sql["trace"]), "trace 记录了生成的 SQL(可调试)")

    print("\n✅ LangGraph 编排验收跑完。")


if __name__ == "__main__":
    main()
