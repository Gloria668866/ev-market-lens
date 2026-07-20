import asyncio, os
from playwright.async_api import async_playwright

OUT = os.path.dirname(os.path.abspath(__file__))
URL = "http://localhost:5173"


async def run():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(viewport={"width": 1280, "height": 860})
        page = await ctx.new_page()
        logs = []
        page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"PAGEERROR: {e}"))

        await page.goto(URL)
        await page.wait_for_load_state("networkidle")

        # 1) 未登录 → 看到登录页（守卫）
        await page.wait_for_selector(".login", timeout=8000)
        guard_ok = await page.locator(".brand-panel h1").count() > 0
        await page.screenshot(path=os.path.join(OUT, "L1-login.png"), full_page=True)

        # 2) 注册账号 A
        await page.click(".tabs button:has-text('注册')")
        await page.wait_for_timeout(300)
        await page.fill(".field:has-text('昵称') input", "分析师A")
        await page.fill(".field:has-text('账号') input", "alice")
        await page.fill(".field:has-text('密码') input >> nth=0", "alice123")
        await page.fill(".field:has-text('确认密码') input", "alice123")
        await page.click(".submit")
        # 进入主界面
        await page.wait_for_selector(".app", timeout=8000)
        await page.wait_for_selector(".ex-card", timeout=8000)
        topbar_user = (await page.locator(".topbar .uname").inner_text()) if await page.locator(".topbar .uname").count() else ""

        # 3) A 提问，生成一条会话
        await page.locator(".ex-card").nth(0).click()
        await page.wait_for_selector("canvas", timeout=12000)
        await page.wait_for_timeout(2500)
        a_convs = await page.locator(".history .conv").count()
        await page.screenshot(path=os.path.join(OUT, "L2-chat.png"), full_page=True)

        # 4) 退出登录 → 回登录页
        await page.click(".topbar .user")
        await page.wait_for_timeout(200)
        await page.click(".menu .mu-item")
        await page.wait_for_selector(".login", timeout=8000)

        # 5) 注册账号 B，应看不到 A 的会话（数据隔离）
        await page.click(".tabs button:has-text('注册')")
        await page.wait_for_timeout(300)
        await page.fill(".field:has-text('昵称') input", "分析师B")
        await page.fill(".field:has-text('账号') input", "bob")
        await page.fill(".field:has-text('密码') input >> nth=0", "bob12345")
        await page.fill(".field:has-text('确认密码') input", "bob12345")
        await page.click(".submit")
        await page.wait_for_selector(".app", timeout=8000)
        await page.wait_for_timeout(500)
        b_convs = await page.locator(".history .conv").count()

        # 6) 退出 → 用 A 登录，应恢复 A 的会话（持久化 + 隔离）
        await page.click(".topbar .user"); await page.wait_for_timeout(200)
        await page.click(".menu .mu-item")
        await page.wait_for_selector(".login", timeout=8000)
        # 默认就是登录 tab
        await page.fill(".field:has-text('账号') input", "alice")
        await page.fill(".field:has-text('密码') input >> nth=0", "alice123")
        await page.click(".submit")
        await page.wait_for_selector(".app", timeout=8000)
        await page.wait_for_timeout(500)
        a_again = await page.locator(".history .conv").count()

        lines = [
            "=== AUTH SMOKE ===",
            f"guard(未登录显示登录页)={guard_ok}",
            f"A 顶栏昵称={topbar_user!r}",
            f"A 会话数={a_convs}  B 会话数={b_convs}（应为0=隔离）  A 重登恢复={a_again}",
            "隔离判定=" + ("PASS" if (a_convs >= 1 and b_convs == 0 and a_again >= 1) else "FAIL"),
            "CONSOLE ERRORS: " + str([l for l in logs if l.startswith('PAGEERROR') or l.startswith('error:')] or 'none'),
        ]
        with open(os.path.join(OUT, "auth_out.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print("\n".join(lines))
        await b.close()


asyncio.run(run())
