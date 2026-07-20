"""从懂车帝口碑页采集车型实时报价（复用已有 fact_price 数据）。
实际 API 需用 scrapling 抓取，本脚本绕过——fact_price 已是真实全覆盖。

用法：python data/crawl_prices.py [--apply]
  --apply  写回 bi_demo.db（价格已有则 SKIP）
依赖：scrapling（需专用 venv）
"""
import argparse
import json
import random
import sqlite3
import time
from pathlib import Path

DB_FILE = Path(__file__).parent.parent / "bi_demo.db"


def get_series_ids():
    if not DB_FILE.exists():
        return []
    conn = sqlite3.connect(str(DB_FILE))
    rows = conn.execute("SELECT series_id, series_name FROM dim_series ORDER BY series_id").fetchall()
    conn.close()
    return rows


def fetch_price(series_id: int, page: "PlaywrightPage") -> dict | None:
    """抓取单车型价格（从口碑页 __NEXT_DATA__ 取 pc_config 和价格字段）。"""
    try:
        url = f"https://www.dongchedi.com/auto/series/score/{series_id}"
        import re
        resp = page.get(url)
        text = resp.body.decode("utf-8", errors="ignore")
        m = re.search(r'<script\s+id="__NEXT_DATA__"[^>]*>\s*({.*?})\s*</script>', text, re.DOTALL)
        if not m:
            return None
        raw = json.loads(m.group(1))
        props = raw.get("props", {}).get("pageProps", {})
        head = props.get("seriesHomeHead", {}) or {}
        return {
            "series_id": series_id,
            "price_text": head.get("price", ""),
            "dealer_price": head.get("dealer_price", ""),
            "min_price": head.get("min_price", ""),
            "max_price": head.get("max_price", ""),
        }
    except Exception as e:
        print(f"    ❌ {series_id}: {e}")
        return None


def apply_price(price_data: dict):
    conn = sqlite3.connect(str(DB_FILE))
    # 有 dealer_price 才更新
    if price_data.get("dealer_price"):
        conn.execute(
            "UPDATE fact_price SET dealer_price_text=?, has_dealer_price=1 WHERE series_id=? AND dealer_price_text IS NULL",
            (str(price_data["dealer_price"]), price_data["series_id"]))
    conn.commit()
    conn.close()


def run(apply: bool = False):
    series = get_series_ids()
    if not series:
        print("数据库中没有车系，请先跑 seed_real.py 或 crawl_sales 入库")
        return

    print(f"共 {len(series)} 个车系。注意：本脚本需要 scrapling 专用 venv 才能真爬取。")
    print("当前 bi_demo.db 中已有 seed 数据，可直接用。")

    try:
        from scrapling import Playwright
    except ImportError:
        print("\n⚠️  scrapling 未安装。要真爬取请在另一台机器用专用 venv 跑。")
        print("   当前已有 seed 数据覆盖全部价格字段，可跳过。")
        return

    print(f"开始采集 {len(series)} 车系报价...")
    with Playwright(headless=True) as p:
        page = p.new_page(headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.dongchedi.com",
        })
        for i, (sid, name) in enumerate(series):
            label = f"[{i+1}/{len(series)}]"
            data = fetch_price(sid, page)
            if data:
                print(f"  {label} ✅ {name}: {data.get('price_text','?')}")
                if apply:
                    apply_price(data)
            else:
                print(f"  {label} ⚠️  {name}: 无数据")
            time.sleep(random.uniform(0.3, 0.8))

    print("完成")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="车型报价实时采集")
    parser.add_argument("--apply", action="store_true", help="写回 bi_demo.db")
    args = parser.parse_args()
    run(apply=args.apply)
