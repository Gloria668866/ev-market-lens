"""从 bi_demo.db 导出车系报价数据供前端 mock 浏览。

用法：python data/export_prices.py
产物：frontend/src/api/prices.json
"""
import json
import sqlite3
import sys
from pathlib import Path

DB_FILE = Path(__file__).parent.parent / "bi_demo.db"
OUT_FILE = Path(__file__).parent.parent / "frontend" / "src" / "api" / "prices.json"


def export():
    if not DB_FILE.exists():
        print(f"[skip] 分析库不存在：{DB_FILE}")
        return

    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT DISTINCT
            s.series_id, s.series_name, s.brand_id, b.brand_name,
            s.segment, s.powertrain, s.endurance_km,
            s.guide_price_min, s.guide_price_max
        FROM dim_series s
        JOIN dim_brand b ON s.brand_id = b.brand_id
        WHERE s.guide_price_min IS NOT NULL
        ORDER BY s.guide_price_min
    """).fetchall()
    conn.close()

    prices = [dict(r) for r in rows]
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(prices, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"导出 {len(prices)} 个车系报价 → {OUT_FILE}")


if __name__ == "__main__":
    export()
