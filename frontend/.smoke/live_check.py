"""live 联调：暗色前端(静态托管) → 连真后端(:8000) → demo 登录 → 提 SQL 问题 → 等真 SSE 出图表。
用法：SMOKE_URL=http://127.0.0.1:8899 python frontend/.smoke/live_check.py（前端 .env=live，后端在 :8000）。"""
import asyncio
import os
from playwright.async_api import async_playwright

OUT = os.path.dirname(os.path.abspath(__file__))
URL = os.environ.get("SMOKE_URL", "http://127.0.0.1:8899")


async def run():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-proxy-server", "--proxy-bypass-list=*"])
        page = await b.new_page(viewport={"width": 1280, "height": 940})
        logs = []
        page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"PAGEERROR: {e}"))
        await page.goto(URL)
        await page.wait_for_load_state("networkidle")

        await page.wait_for_selector(".demo", timeout=8000)
        await page.click(".demo")                                  # live：调真后端 register/login
        await page.wait_for_selector(".ex-card", timeout=20000)    # 登录成功 → 主界面
        logged_in = await page.locator(".ex-card").count() > 0

        await page.locator(".ex-card").first.click()               # 提 SQL 示例问题
        await page.wait_for_selector("canvas", timeout=60000)      # 真后端 LLM+SQL 较慢
        await page.wait_for_selector(".insight-body", timeout=60000)
        await page.wait_for_timeout(3500)
        has_canvas = await page.locator("canvas").count() > 0
        insight = (await page.locator(".insight-body").first.inner_text())[:50]
        await page.screenshot(path=os.path.join(OUT, "live-data.png"), full_page=True)

        errors = [l for l in logs if l.startswith("PAGEERROR") or l.startswith("error:")]
        print("=== LIVE 联调 ===")
        print(f"logged_in={logged_in} canvas={has_canvas}")
        print(f"insight: {insight!r}")
        print("CONSOLE ERRORS: " + str(errors or "none"))
        await b.close()


asyncio.run(run())
