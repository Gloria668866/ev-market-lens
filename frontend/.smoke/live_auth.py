import asyncio, os, time
from playwright.async_api import async_playwright

OUT = os.path.dirname(os.path.abspath(__file__))
URL = "http://localhost:5173"


async def run():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await (await b.new_context(viewport={"width": 1280, "height": 860})).new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(f"PAGEERROR: {e}"))
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

        await page.goto(URL)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_selector(".login", timeout=8000)

        # 通过真实后端注册（register→自动 login）
        u = f"uitest{int(time.time())}"
        await page.click(".tabs button:has-text('注册')")
        await page.wait_for_timeout(300)
        await page.fill(".field:has-text('昵称') input", "界面联调")
        await page.fill(".field:has-text('账号') input", u)
        await page.fill(".field:has-text('密码') input >> nth=0", "pw12345")
        await page.fill(".field:has-text('确认密码') input", "pw12345")
        await page.click(".submit")

        ok = True
        try:
            await page.wait_for_selector(".app", timeout=10000)
        except Exception:
            ok = False
        await page.wait_for_timeout(600)
        topname = (await page.locator(".topbar .uname").inner_text()) if await page.locator(".topbar .uname").count() else ""
        token = await page.evaluate("() => localStorage.getItem('cheshijing.token')")
        login_err = (await page.locator(".login .err").inner_text()) if await page.locator(".login .err").count() else ""

        lines = [
            "=== LIVE AUTH (真后端) ===",
            f"注册→进入主界面={ok}",
            f"顶栏昵称={topname!r}",
            f"token存在={bool(token)} 前缀={ (token or '')[:16] }",
            f"登录页报错={login_err!r}",
            "CONSOLE/PAGE ERRORS: " + str([e for e in errs if 'PAGEERROR' in e or 'favicon' not in e][:5] or 'none'),
        ]
        with open(os.path.join(OUT, "live_out.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print("\n".join(lines))
        await b.close()


asyncio.run(run())
