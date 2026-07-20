"""清洗入库脚本（T4）：raw JSONL → 清洗 → 拆 6 表 → SQLite bi_demo.db（幂等 UPSERT）。

数据流：
  data/raw/sales_rank_raw.jsonl
       ↓  字段重命名 / 类型转换 / 空值处理 / 去重
  bi_demo.db（6 张表，Kimball 星型模型）
  ├── dim_brand      (101 品牌)
  ├── dim_series     (409 车系，含 segment / endurance_km 口碑页补充)
  ├── dim_date       (YYYYMM 日期维度)
  ├── fact_sales_rank (销量事实，UNIQUE 防重复 UPSERT)
  ├── fact_price      (报价快照)
  └── fact_review     (口碑评分)

运行：python data/clean_load.py
"""
import json
import re
import sqlite3
from pathlib import Path

RAW_FILE = Path(__file__).parent / "raw" / "sales_rank_raw.jsonl"
DB_FILE  = Path(__file__).parent.parent / "bi_demo.db"


# ------------------------------------------------------------------ 字段清洗函数
def parse_price(text: str | None) -> tuple[float | None, float | None]:
    """'26.98-34.98万' → (26.98, 34.98)；解析失败返回 (None, None)。"""
    if not text:
        return None, None
    nums = re.findall(r"\d+\.?\d*", str(text))
    if len(nums) >= 2:
        return float(nums[0]), float(nums[-1])
    if len(nums) == 1:
        v = float(nums[0])
        return v, v
    return None, None


# 别名：测试与外部调用统一用 parse_price_range
parse_price_range = parse_price


def parse_month(yyyymm_str: str) -> tuple[int, int, int, int, str]:
    """'202503' → (202503, 2025, 3, 1, '2025-03')：date_id / year / month / quarter / ym。"""
    yyyymm = int(yyyymm_str)
    y, m = yyyymm // 100, yyyymm % 100
    q = (m - 1) // 3 + 1
    return (yyyymm, y, m, q, f"{y}-{m:02d}")


def clean_rank(rank) -> tuple:
    """0 / None → (None, True=新上榜)；有效排名 → (rank, False)。"""
    if not rank:
        return (None, True)
    return (rank, False)


def parse_endurance(text: str | None) -> int | None:
    """'593-821km' → 821（区间取上限）；'500km' → 500；'-' → None。"""
    if not text or str(text).strip() in ("-", "", "暂无", "—"):
        return None
    nums = re.findall(r"\d+", str(text))
    return int(nums[-1]) if nums else None


def norm_score(score) -> float | None:
    """懂车帝评分 ×100 整数 → 浮点分数；0 / None → None。"""
    if not score:
        return None
    return round(float(score) / 100, 1)


def norm_text(text: str | None) -> str | None:
    """去首尾空白；纯空字符串 → None。"""
    if text is None:
        return None
    s = str(text).strip()
    return s if s else None


def infer_powertrain(energy_type: int) -> str:
    """懂车帝 new_energy_type 枚举 → 内部 powertrain 标签。"""
    return {1: "BEV", 2: "PHEV", 3: "EREV"}.get(energy_type, "NEV")


# ------------------------------------------------------------------ DDL
DDL = """
CREATE TABLE IF NOT EXISTS dim_brand (
    brand_id   INTEGER PRIMARY KEY,
    brand_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dim_series (
    series_id      INTEGER PRIMARY KEY,
    series_name    TEXT NOT NULL,
    brand_id       INTEGER REFERENCES dim_brand(brand_id),
    segment        TEXT,
    powertrain     TEXT,
    endurance_km   INTEGER,
    guide_price_min REAL,
    guide_price_max REAL,
    image_url      TEXT
);
CREATE TABLE IF NOT EXISTS dim_date (
    date_id INTEGER PRIMARY KEY,   -- YYYYMM
    year    INTEGER,
    month   INTEGER,
    quarter INTEGER,
    ym      TEXT
);
CREATE TABLE IF NOT EXISTS fact_sales_rank (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id        INTEGER REFERENCES dim_series(series_id),
    date_id          INTEGER REFERENCES dim_date(date_id),
    new_energy_type  INTEGER,
    rank_type        INTEGER DEFAULT 11,
    rank             INTEGER,
    last_rank        INTEGER,
    volume           INTEGER,
    crawl_time       TEXT,
    UNIQUE(series_id, date_id, new_energy_type, rank_type)
);
CREATE TABLE IF NOT EXISTS fact_price (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id         INTEGER REFERENCES dim_series(series_id),
    date_id           INTEGER REFERENCES dim_date(date_id),
    guide_price_min   REAL,
    guide_price_max   REAL,
    price_text        TEXT,
    dealer_price_text TEXT,
    has_dealer_price  INTEGER DEFAULT 0,
    descender_price   REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fact_review (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id    INTEGER REFERENCES dim_series(series_id),
    date_id      INTEGER REFERENCES dim_date(date_id),
    review_count INTEGER,
    score        REAL
);
"""


# ------------------------------------------------------------------ 主流程
def run():
    if not RAW_FILE.exists():
        raise SystemExit(f"原始数据不存在：{RAW_FILE}\n请先运行 data/crawl_sales.py")

    print(f"读取 {RAW_FILE} ...")
    rows = [json.loads(line) for line in RAW_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"共 {len(rows)} 行原始记录")

    conn = sqlite3.connect(DB_FILE)
    conn.executescript(DDL)

    brands, series, dates = {}, {}, {}

    for r in rows:
        # 维度去重收集
        brands[r["brand_id"]] = r["brand_name"]
        series[r["series_id"]] = {
            "series_name": r["series_name"],
            "brand_id":    r["brand_id"],
            "powertrain":  infer_powertrain(r["_new_energy_type"]),
        }
        yyyymm = int(r["_month"])
        if yyyymm not in dates:
            y, m = yyyymm // 100, yyyymm % 100
            dates[yyyymm] = {"year": y, "month": m, "quarter": (m - 1) // 3 + 1, "ym": r["_month"]}

    # 写维度表
    conn.executemany("INSERT OR IGNORE INTO dim_brand VALUES(?,?)", brands.items())
    conn.executemany(
        "INSERT OR IGNORE INTO dim_series(series_id,series_name,brand_id,powertrain) VALUES(?,?,?,?)",
        [(sid, v["series_name"], v["brand_id"], v["powertrain"]) for sid, v in series.items()])
    conn.executemany(
        "INSERT OR IGNORE INTO dim_date VALUES(?,?,?,?,?)",
        [(k, v["year"], v["month"], v["quarter"], v["ym"]) for k, v in dates.items()])

    # 写事实表
    for r in rows:
        pmin, pmax = parse_price(r.get("min_price") or r.get("max_price"))
        _, pmax2   = parse_price(r.get("max_price"))
        last_rank  = r.get("last_rank") or None   # 0 = 新上榜 → NULL
        if last_rank == 0:
            last_rank = None
        volume     = r.get("count") or 0
        date_id    = int(r["_month"])

        conn.execute(
            "INSERT OR REPLACE INTO fact_sales_rank"
            "(series_id,date_id,new_energy_type,rank_type,rank,last_rank,volume,crawl_time)"
            " VALUES(?,?,?,11,?,?,?,datetime('now'))",
            (r["series_id"], date_id, r["_new_energy_type"],
             r.get("rank"), last_rank, volume))

        conn.execute(
            "INSERT OR IGNORE INTO fact_price"
            "(series_id,date_id,guide_price_min,guide_price_max,price_text,dealer_price_text,has_dealer_price)"
            " VALUES(?,?,?,?,?,?,?)",
            (r["series_id"], date_id, pmin, pmax2 or pmax,
             r.get("min_price"), r.get("dealer_price"),
             1 if r.get("dealer_price") else 0))

        conn.execute(
            "INSERT OR IGNORE INTO fact_review(series_id,date_id,review_count,score) VALUES(?,?,?,NULL)",
            (r["series_id"], date_id, r.get("car_review_count") or 0))

    conn.commit()

    # 验收统计
    for tbl in ("dim_brand", "dim_series", "dim_date", "fact_sales_rank", "fact_price", "fact_review"):
        cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {cnt} 行")

    conn.close()
    print(f"\n入库完成 → {DB_FILE}")


if __name__ == "__main__":
    run()
