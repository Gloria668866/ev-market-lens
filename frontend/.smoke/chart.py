import asyncio, os, time
from playwright.async_api import async_playwright

OUT = os.path.dirname(os.path.abspath(__file__))
URL = "http://localhost:5173"


async def run():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await (await b.new_context(viewport={"width": 1280, "height": 900})).new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(f"PAGEERROR: {e}"))
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

        await page.goto(URL); await page.wait_for_load_state("networkidle")
        # 登录（mock 一键演示）
        await page.wait_for_selector(".login", timeout=8000)
        await page.click(".demo")
        await page.wait_for_selector(".app", timeout=8000)
        await page.wait_for_selector(".ex-card", timeout=8000)

        # 问一个数据分析问题
        await page.locator(".ex-card").nth(0).click()
        await page.wait_for_selector(".chart-card canvas", timeout=12000)
        await page.wait_for_timeout(2500)

        # 1) 不再有「查看 SQL / 查看数据表」
        no_sql = await page.locator("text=查看 SQL").count() == 0
        no_tbl = await page.locator("text=查看数据表").count() == 0
        # 2) 切换器 4 个按钮
        btns = page.locator(".switch button")
        nbtn = await btns.count()
        labels = [await btns.nth(i).inner_text() for i in range(nbtn)]
        # 5) 默认高亮 = 柱状图
        default_on = await page.locator(".switch button.on").inner_text()

        shots = {}
        async def shot(name):
            await page.wait_for_timeout(700)
            await page.screenshot(path=os.path.join(OUT, f"C-{name}.png"), full_page=True)

        await shot("default-bar")
        # 3)+4) 逐个切换，确认 canvas 仍在、legend 存在（option 注入后画布重绘）
        results = {}
        for label in ["折线图", "饼图", "横向条形", "柱状图"]:
            await page.locator(f".switch button:has-text('{label}')").click()
            await page.wait_for_timeout(500)
            on = await page.locator(".switch button.on").inner_text()
            canvas = await page.locator(".chart-card canvas").count()
            results[label] = (on == label and canvas > 0)
        await shot("after-pie")  # last set was 柱状图 actually; capture final

        # 切到饼图再截一张做视觉确认
        await page.locator(".switch button:has-text('饼图')").click(); await shot("pie")
        await page.locator(".switch button:has-text('折线图')").click(); await shot("line")

        lines = [
            "=== CHART SWITCHER ===",
            f"无『查看SQL』={no_sql}  无『查看数据表』={no_tbl}",
            f"切换按钮数={nbtn} 标签={labels}",
            f"默认高亮={default_on!r}（应=柱状图）",
            f"逐类切换OK={results}",
            "ERRORS: " + str([e for e in errs if 'PAGEERROR' in e or ('favicon' not in e and 'font' not in e.lower())][:5] or 'none'),
        ]
        with open(os.path.join(OUT, "chart_out.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print("\n".join(lines))
        await b.close()


asyncio.run(run())
