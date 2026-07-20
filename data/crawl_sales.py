"""懂车帝销量榜增量采集脚本（T3 正式采集）。

数据源：懂车帝公开销量榜 API（免登录，带 Referer 即可）
接口：GET https://www.dongchedi.com/motor/pc/car/rank_data
参数说明：
  rank_data_type = 11         销量榜（固定）
  new_energy_type = 0/1/2/3   0全部 1纯电 2插混 3增程
  month = YYYYMM              留空=最新月，填月份=历史回溯
  count / offset              翻页（每页50条）

产物：data/raw/sales_rank_raw.jsonl（每行一条车系月度销量记录）
运行：python data/crawl_sales.py --start 202401 --end 202604
依赖：pip install scrapling  （需用专用 venv，系统 Python 3.14 不兼容）
"""
import argparse
import json
import random
import time
from pathlib import Path

# ------------------------------------------------------------------ 常量
API_URL = "https://www.dongchedi.com/motor/pc/car/rank_data"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.dongchedi.com/sales",
    "Accept": "application/json, text/plain, */*",
}
# 三种能源类型分别采：1=纯电 2=插混 3=增程（0=全部会重复，不取）
ENERGY_TYPES = [1, 2, 3]
PAGE_SIZE = 50
OUT_FILE = Path(__file__).parent / "raw" / "sales_rank_raw.jsonl"


# ------------------------------------------------------------------ 月份工具
def month_range(start: str, end: str) -> list[str]:
    """生成 YYYYMM 列表，跨年处理。
    例：month_range('202411','202502') → ['202411','202412','202501','202502']
    """
    result = []
    y, m = int(start[:4]), int(start[4:])
    ey, em = int(end[:4]), int(end[4:])
    while (y, m) <= (ey, em):
        result.append(f"{y}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result


# ------------------------------------------------------------------ 单月单能源采集
def fetch_month(month: str, energy_type: int, page: "PlaywrightPage") -> list[dict]:
    """爬一个月×能源类型的全部分页，返回原始记录列表。"""
    records = []
    offset = 0
    while True:
        url = (
            f"{API_URL}?rank_data_type=11"
            f"&new_energy_type={energy_type}"
            f"&month={month}"
            f"&count={PAGE_SIZE}&offset={offset}"
        )
        resp = page.get(url)                   # scrapling: page.get() 返回 Response
        raw = json.loads(resp.body)            # 取 bytes，不用 str(resp)（那是 repr）
        items = raw.get("data", {}).get("list") or []
        if not items:
            break
        for item in items:
            records.append({
                "_month": month,
                "_new_energy_type": energy_type,
                "series_id":    item.get("series_id"),
                "series_name":  item.get("series_name"),
                "brand_id":     item.get("brand_id"),
                "brand_name":   item.get("brand_name"),
                "count":        item.get("count"),          # 销量（月度）
                "rank":         item.get("rank"),
                "last_rank":    item.get("last_rank"),      # 上月排名，0=新上榜
                "min_price":    item.get("min_price"),      # 指导价下限（万元字符串）
                "max_price":    item.get("max_price"),
                "dealer_price": item.get("dealer_price"),   # 经销商成交价区间
                "car_review_count": item.get("car_review_count"),
            })
        offset += PAGE_SIZE
        if len(items) < PAGE_SIZE:
            break
        time.sleep(random.uniform(0.3, 0.8))  # 随机延时防封
    return records


# ------------------------------------------------------------------ 主流程
def run(start: str, end: str):
    try:
        from scrapling import Playwright
    except ImportError:
        raise SystemExit(
            "scrapling 未安装。请用专用 venv：\n"
            r"  C:\Users\Lenovo\.claude\skills\scrapling\.venv\Scripts\python.exe data/crawl_sales.py"
        )

    months = month_range(start, end)
    print(f"计划采集：{len(months)} 个月 × {len(ENERGY_TYPES)} 种能源 = {len(months)*len(ENERGY_TYPES)} 批次")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    total = 0

    with Playwright(headless=True) as p:
        page = p.new_page(headers=HEADERS)
        with OUT_FILE.open("a", encoding="utf-8") as f:
            for month in months:
                for et in ENERGY_TYPES:
                    label = {1: "纯电", 2: "插混", 3: "增程"}[et]
                    records = fetch_month(month, et, page)
                    for r in records:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    total += len(records)
                    print(f"  {month} {label}: {len(records)} 条")
                    time.sleep(random.uniform(0.5, 1.2))

    print(f"\n完成！共写入 {total} 行 → {OUT_FILE}")


# ------------------------------------------------------------------ CLI
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="懂车帝销量榜采集")
    parser.add_argument("--start", default="202401", help="起始月份 YYYYMM")
    parser.add_argument("--end",   default="202604", help="结束月份 YYYYMM")
    args = parser.parse_args()
    run(args.start, args.end)
