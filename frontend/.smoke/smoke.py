"""车市镜前端冒烟（mock 链路，Playwright async API）。
覆盖：登录守卫 → 一键演示登录 → SQL 双脑（图表+切换器+无SQL/数据表）→ RAG（引用卡+章节heading_path+溯源）
→ 知识库（上传→解析进度parsing→ready→删除）→ 历史会话还原。
需 dev server 跑在 5173（mock 模式，用 .env.local 覆盖）。"""
import asyncio
import os
from playwright.async_api import async_playwright

OUT = os.path.dirname(os.path.abspath(__file__))
URL = os.environ.get("SMOKE_URL", "http://localhost:5173")


async def run():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-proxy-server", "--proxy-bypass-list=*"])
        page = await b.new_page(viewport={"width": 1280, "height": 940})
        logs = []
        page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"PAGEERROR: {e}"))
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))  # 删除确认框自动同意

        await page.goto(URL)
        await page.wait_for_load_state("networkidle")

        # —— 1. 登录守卫 → 一键演示登录 —— #
        await page.wait_for_selector(".demo", timeout=8000)
        guard_blocks = await page.locator(".ex-card").count() == 0   # 未登录看不到主界面
        await page.wait_for_timeout(500)
        await page.screenshot(path=os.path.join(OUT, "0-login.png"), full_page=True)  # 暗色登录页自查
        await page.click(".demo")
        await page.wait_for_selector(".ex-card", timeout=8000)
        ex = page.locator(".ex-card")
        ex_n = await ex.count()
        await page.screenshot(path=os.path.join(OUT, "1-empty.png"), full_page=True)

        # —— 2. SQL 双脑：图表 + 切换器 + 无 SQL/数据表 —— #
        await ex.nth(0).click()
        await page.wait_for_selector("canvas", timeout=12000)
        await page.wait_for_selector(".insight-body", timeout=12000)
        await page.wait_for_timeout(2200)
        no_sql = await page.locator("text=查看 SQL").count() == 0
        no_table = await page.locator("text=查看数据表").count() == 0
        switch_btns = await page.locator(".switch button").count()
        intent_sql = await page.locator(".intent-tag.sql").count() > 0
        has_canvas = await page.locator("canvas").count() > 0
        switched = False
        if switch_btns > 1:                       # 切到第二个图型，前端重绘，canvas 仍在
            await page.locator(".switch button").nth(1).click()
            await page.wait_for_timeout(500)
            switched = await page.locator("canvas").count() > 0
        await page.screenshot(path=os.path.join(OUT, "2-sql.png"), full_page=True)

        # —— 3. RAG：引用卡 + 章节 heading_path + 点击溯源 —— #
        await page.click("text=新建对话")
        await page.wait_for_timeout(300)
        await page.locator(".ex-card", has_text="行研报告").click()
        await page.wait_for_selector(".cite", timeout=15000)
        await page.wait_for_timeout(1800)
        cite_count = await page.locator(".cite").count()
        has_path = await page.locator(".cite .path").count() > 0
        intent_rag = await page.locator(".intent-tag.rag").count() > 0
        await page.locator(".cite").first.click()
        await page.wait_for_timeout(300)
        trace_box = await page.locator(".trace-box").count() > 0
        await page.screenshot(path=os.path.join(OUT, "3-rag.png"), full_page=True)

        # —— 4. 历史会话还原：点回更早的 SQL 会话，应还原出图表 —— #
        convs = page.locator(".conv")
        conv_n = await convs.count()
        restored = False
        if conv_n >= 2:
            await convs.nth(1).click()            # [0]=RAG(最新), [1]=SQL(更早)
            await page.wait_for_timeout(700)
            restored = await page.locator("canvas").count() > 0

        # —— 5. 知识库：上传 → 解析进度 → 就绪 → 删除 —— #
        await page.click(".kb-entry")
        await page.wait_for_selector(".modal", timeout=5000)
        await page.wait_for_timeout(300)
        docs0 = await page.locator(".modal .doc").count()
        await page.set_input_files(".modal input[type=file]", files=[
            {"name": "测试研报.txt", "mimeType": "text/plain", "buffer": b"hello cheshijing kb"}])
        await page.wait_for_selector(".modal .dstatus.warn", timeout=6000)
        parsing_seen = await page.locator(".modal .dstatus.warn").count() > 0
        await page.wait_for_selector(".modal .doc .dstatus.ok", timeout=10000)
        await page.wait_for_timeout(400)
        docs1 = await page.locator(".modal .doc").count()
        uploaded = docs1 > docs0
        await page.screenshot(path=os.path.join(OUT, "4-kb.png"), full_page=True)
        await page.locator(".modal .doc").first.hover()
        await page.locator(".modal .del").first.click()
        await page.wait_for_timeout(600)
        docs2 = await page.locator(".modal .doc").count()
        deleted = docs2 < docs1

        errors = [l for l in logs if l.startswith('PAGEERROR') or l.startswith('error:')]
        lines = [
            "=== SMOKE RESULTS (mock) ===",
            f"AUTH: guard_blocks={guard_blocks} demo_login_ok={ex_n == 4}",
            f"SQL : canvas={has_canvas} no_sql={no_sql} no_table={no_table} switch_btns={switch_btns} switched={switched} intent_sql={intent_sql}",
            f"RAG : cites={cite_count} heading_path={has_path} trace_box={trace_box} intent_rag={intent_rag}",
            f"HIST: restored_chart={restored} (convs={conv_n})",
            f"KB  : parsing_seen={parsing_seen} uploaded={uploaded} deleted={deleted} (docs {docs0}->{docs1}->{docs2})",
            "CONSOLE ERRORS: " + str(errors or 'none'),
        ]
        out = "\n".join(lines)
        with open(os.path.join(OUT, "out.txt"), "w", encoding="utf-8") as f:
            f.write(out)
        print(out)
        await b.close()


asyncio.run(run())
