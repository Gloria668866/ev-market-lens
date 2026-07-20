"""懂车帝销量榜 API 探针脚本（T1 数据探索）。
用来探查接口字段、数据量和可用性，为 schema 设计提供依据。

用法：python data/probe/probe.py
产物：data/probe/*.json（原始响应样本）
"""
import json
from pathlib import Path

API_URL = "https://www.dongchedi.com/motor/pc/car/rank_data"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.dongchedi.com/sales",
    "Accept": "application/json, text/plain, */*",
}
OUT_DIR = Path(__file__).parent


def probe_single(month: str = "", energy_type: int = 1, count: int = 50):
    """探查单个请求，返回原始 JSON + 字段列表。"""
    try:
        from scrapling import Playwright
    except ImportError:
        # Fallback: 用 requests（可能被限，但探针够用）
        import requests
        url = f"{API_URL}?rank_data_type=11&new_energy_type={energy_type}&month={month}&count={count}&offset=0"
        resp = requests.get(url, headers=HEADERS, timeout=30)
        data = resp.json()
        items = data.get("data", {}).get("list") or []
        total = data.get("data", {}).get("total", 0)
        print(f"  month={month or '最新'}  energy_type={energy_type}  total={total}  items={len(items)}")
        if items:
            print(f"  🔑 字段：{list(items[0].keys())}")
            print(f"  样例：series_name={items[0].get('series_name')}  count={items[0].get('count')}  rank={items[0].get('rank')}")
        return items
    else:
        # scrapling 可用时走浏览器级请求
        with Playwright(headless=True) as p:
            page = p.new_page(headers=HEADERS)
            url = f"{API_URL}?rank_data_type=11&new_energy_type={energy_type}&month={month}&count={count}&offset=0"
            resp = page.get(url)
            data = json.loads(resp.body)
            items = data.get("data", {}).get("list") or []
            print(f"  month={month or '最新'}  energy_type={energy_type}  items={len(items)}")
            if items:
                print(f"  🔑 字段：{list(items[0].keys())}")
            return items


def probe_volume():
    """探查历史数据的可用范围和总量。"""
    print("=== 数据量探针 ===")
    months_to_test = ["202401", "202406", "202412", "202504"]
    for energy_type in [0, 1, 2, 3]:
        label = {0: "全部", 1: "纯电", 2: "插混", 3: "增程"}[energy_type]
        total_items = 0
        for m in months_to_test:
            try:
                items = probe_single(m, energy_type, count=50)
                total_items += len(items)
            except Exception as e:
                print(f"    ❌ month={m}: {e}")
        print(f"  → {label}: 4个月合计 {total_items} 条")


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=== 字段探针（最新月，纯电）===")
    try:
        items = probe_single("", 1, 50)
        if items:
            # 保存样例
            sample_file = OUT_DIR / "probe_sample.json"
            # 只存前3条
            sample_file.write_text(json.dumps(items[:3], ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  样例已保存 → {sample_file}")
            # 输出字段清单
            fields_file = OUT_DIR / "字段枚举.txt"
            lines = ["# 懂车帝销量榜 API 实测字段\n"]
            for k, v in items[0].items():
                lines.append(f"{k}: {type(v).__name__}  = {v!r}")
            fields_file.write_text("\n".join(lines), encoding="utf-8")
            print(f"  字段清单 → {fields_file}")
    except Exception as e:
        print(f"  ❌ 探针失败：{e}")
        print("  (网络不通或接口变更——当前环境可能无法直连懂车帝)")

    print("\n=== 数据量探针 ===")
    try:
        probe_volume()
    except Exception as e:
        print(f"  ❌ 数据量探针失败：{e}")
