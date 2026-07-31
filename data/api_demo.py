#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API/SSE 协议对齐 E2E 验收（PRD-2 §9.1 SSE 协议 + §10 接口 / DoD）。

验：1) /api/ask 严格按 §9.1 发 intent/sql/rows/chart/insight/citation/done(纯RAG无sql/rows/chart)；
    2) chart 是描述符(default_type/applicable_types/dimension/measures/title)；
    3) kb 上传→解析→ready→可问答 闭环；4) history 能还原含图表/引用的会话；5) 未鉴权 401。

为全栈一致，app 跑在 PG（用户/会话/消息与 kb 同库）。用独立测试用户，与后台 KB 构建互不干扰。
运行：HF_HUB_OFFLINE=1 PYTHONUTF8=1 .venv/Scripts/python.exe data/api_demo.py
"""
import json, os, sys, time, random
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 关键：导入 app 前把应用库指到 PG（load_dotenv 不覆盖已存在的 env）
os.environ["APP_DATABASE_URL"] = "postgresql+psycopg://app_rw:app_rw_pass_change_me@localhost:5433/app"

from fastapi.testclient import TestClient
from app.main import app
from app.rag import ingest

client = TestClient(app)
U = f"api_demo_{random.randint(1000,9999)}"


def ok(c, m): print(f"  [{'PASS' if c else 'FAIL'}] {m}"); return c


def sse(question, token, conv_id=None):
    """POST /api/ask 收 SSE，返回 [{event,data}]。"""
    body = {"question": question}
    if conv_id:
        body["conversation_id"] = conv_id
    evs, cur = [], {}
    with client.stream("POST", "/api/ask", json=body, headers={"Authorization": f"Bearer {token}"}) as r:
        for line in r.iter_lines():
            line = line.strip()
            if line.startswith("event:"):
                cur["event"] = line[6:].strip()
            elif line.startswith("data:"):
                cur["data"] = line[5:].strip()
            elif not line and cur:
                evs.append(cur); cur = {}
    if cur:
        evs.append(cur)
    return evs


def main():
    # ===== 5) 未鉴权 401（先验）=====
    print("=== 5) 未鉴权被拒 ===")
    r = client.post("/api/ask", json={"question": "x"})
    ok(r.status_code == 401, f"无 token 请求 /api/ask → 401（实际 {r.status_code}）")

    # 注册 + 登录
    client.post("/api/auth/register", json={"username": U, "password": "pw12345", "nickname": "接口测试"})
    tok = client.post("/api/auth/login", json={"username": U, "password": "pw12345"}).json()["access_token"]
    AUTH = {"Authorization": f"Bearer {tok}"}
    print(f"测试用户 {U} 登录 OK")

    # ===== 3) kb 上传 → 解析 → ready → 可问答 =====
    print("\n=== 3) kb 上传→解析→ready→问答 闭环 ===")
    md = ("# 内部测试报告\n\n## 续航结论\n\n根据本内部报告，鲲鹏牌纯电轿车2025款的官方续航达到 1234 公里，"
          "为本测试库独有数据。\n\n## 价格\n\n该车型指导价 18.8 万元起。").encode("utf-8")
    up = client.post("/api/kb/upload", files={"file": ("内部测试报告.md", md, "text/markdown")}, headers=AUTH)
    ok(up.status_code == 200 and up.json()["status"] == "parsing", f"上传返回 parsing（{up.status_code}）")
    doc_id = up.json()["doc_id"]
    # 模拟 Celery worker 同步把它解析入库（worker 没起时）
    ingest.ingest_document(doc_id)
    st = client.get(f"/api/kb/{doc_id}", headers=AUTH).json()
    ok(st["status"] == "ready" and st["chunk_count"] > 0, f"解析后 status=ready chunks={st.get('chunk_count')}")
    ans = client.post("/api/kb/ask", json={"question": "鲲鹏牌纯电轿车续航多少公里？"}, headers=AUTH).json()
    print(f"    答案: {ans['answer'][:70]}")
    ok(ans["has_answer"] and "1234" in ans["answer"] and ans["citations"], "就上传文档问答，答案含1234且带引用")

    # 上传校验
    bad = client.post("/api/kb/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")}, headers=AUTH)
    ok(bad.status_code == 415, f"不支持类型 → 415（实际 {bad.status_code}，结构化错误）")

    # ===== 1)+2) /api/ask SSE 协议（SQL 路）=====
    print("\n=== 1)+2) /api/ask SSE §9.1（数据脑）===")
    evs = sse("2025年纯电销量前5的车系", tok)
    names = [e["event"] for e in evs]
    print(f"    事件序列: {names}")
    ok(names[0] == "intent", "首事件 intent")
    ok("sql" in names and "rows" in names and "chart" in names and "insight" in names and names[-1] == "done", "含 sql/rows/chart/insight，末 done")
    chart_ev = next((e for e in evs if e["event"] == "chart"), None)
    chart = json.loads(chart_ev["data"]) if chart_ev else {}
    ok(all(k in chart for k in ("default_type", "applicable_types", "dimension", "measures", "title")), f"chart 是描述符: default={chart.get('default_type')} applicable={chart.get('applicable_types')}")
    rows_ev = json.loads(next(e for e in evs if e["event"] == "rows")["data"])
    ok(isinstance(rows_ev.get("rows"), list) and isinstance(rows_ev["rows"][0], list), "rows 是 {columns, 数组行}")
    sql_conv = json.loads(next(e for e in evs if e["event"] == "intent")["data"])["conversation_id"]

    # ===== 1) /api/ask SSE 协议（纯 RAG 路：无 sql/rows/chart，有 citation）=====
    print("\n=== 1) /api/ask SSE §9.1（知识脑，纯 RAG）===")
    evr = sse("这份内部测试报告对鲲鹏牌纯电轿车是怎么解读的？", tok)
    namesr = [e["event"] for e in evr]
    print(f"    事件序列: {namesr}")
    ok("sql" not in namesr and "rows" not in namesr and "chart" not in namesr, "纯 RAG 无 sql/rows/chart 事件")
    ok("insight" in namesr and "citation" in namesr and namesr[-1] == "done", "有 insight(答案)+citation，末 done")
    rag_conv = json.loads(next(e for e in evr if e["event"] == "intent")["data"])["conversation_id"]

    # ===== 4) history 还原含图表/引用的会话 =====
    print("\n=== 4) history 还原会话(含图表/引用) ===")
    hl = client.get("/api/history", headers=AUTH).json()
    ok(len(hl["conversations"]) >= 2, f"会话列表 {len(hl['conversations'])} 个")
    d_sql = client.get(f"/api/history/{sql_conv}", headers=AUTH).json()
    asst = next((m for m in d_sql["messages"] if m["role"] == "assistant"), {})
    ok(asst.get("chart") and asst.get("rows"), "SQL 会话的助手消息能还原 chart + rows")
    d_rag = client.get(f"/api/history/{rag_conv}", headers=AUTH).json()
    asst_r = next((m for m in d_rag["messages"] if m["role"] == "assistant"), {})
    ok(bool(asst_r.get("citations")), "RAG 会话的助手消息能还原 citations")
    # 隔离：别的会话 id 拿不到（404 或不属于自己）
    ok(client.get("/api/history/999999", headers=AUTH).status_code == 404, "取不存在/他人会话 → 404")

    # ===== kb 软删 =====
    print("\n=== kb 软删除 ===")
    ok(client.delete(f"/api/kb/{doc_id}", headers=AUTH).json().get("deleted"), "DELETE 软删成功")
    lst = client.get("/api/kb/list", headers=AUTH).json()["documents"]
    ok(all(d["id"] != doc_id for d in lst), "软删后 list 不再含该文档")
    ans2 = client.post("/api/kb/ask", json={"question": "鲲鹏牌纯电轿车续航多少？"}, headers=AUTH).json()
    ok(not ans2["has_answer"], "软删后该内容问不到(检索已排除)")

    print("\n✅ API/SSE 协议验收跑完。")


if __name__ == "__main__":
    main()
