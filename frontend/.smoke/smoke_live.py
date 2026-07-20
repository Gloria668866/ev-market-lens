"""端到端冒烟（LIVE）：前端(5173) 连真后端(8000) 跑一个真实 SQL 问题，截图 + 断言。
前置：后端 uvicorn:8000 已起、前端 .env 设 VITE_DATA_SOURCE=live 且 npm run dev:5173 已起。
RAG 脑后端尚未实现，本脚本只验证数据分析脑（Text2SQL）这条 live 链路。
"""
import asyncio
import os
from playwright.async_api import async_playwright

OUT = os.path.dirname(os.path.abspath(__file__))
URL = "http://localhost:5173"


async def run():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await b.new_page(viewport={"width": 1280, "height": 900})
        logs = []
        page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"PAGEERROR: {e}"))

        await page.goto(URL)
        await page.wait_for_load_state("networkidle")
        await page.screenshot(path=os.path.join(OUT, "live-1-empty.png"), full_page=True)

        # 点第一张示例卡（数据分析类问题）→ 走 live /api/ask
        await page.locator(".ex-card").nth(0).click()
        await page.wait_for_selector("canvas", timeout=60000)          # ECharts 图表渲染出来
        await page.wait_for_selector(".insight-body", timeout=60000)   # 洞察流式区
        await page.wait_for_selector("text=查看 SQL", timeout=60000)   # 可折叠 SQL
        await page.wait_for_timeout(3000)                              # 等洞察流完
        await page.screenshot(path=os.path.join(OUT, "live-2-sql.png"), full_page=True)

        has_canvas = await page.locator("canvas").count() > 0
        has_trace = await page.locator(".trace").count() > 0
        intent_sql = await page.locator(".intent-tag.sql").count() > 0
        await page.click("text=查看 SQL")
        await page.wait_for_timeout(400)
        sql_visible = await page.locator(".sql-box pre").is_visible()
        insight_text = (await page.locator(".insight-body").inner_text())[:60]

        errs = [l for l in logs if l.startswith("PAGEERROR") or l.startswith("error:")]
        print("=== LIVE SMOKE RESULTS ===")
        print(f"chart(canvas)={has_canvas}  thinking-trace={has_trace}  intent=sql:{intent_sql}  sql_fold_visible={sql_visible}")
        print(f"insight 开头: {insight_text!r}")
        print("CONSOLE ERRORS:", errs or "none")
        await b.close()


asyncio.run(run())
