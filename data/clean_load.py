"""清洗入库脚本（T4）：raw JSONL → 清洗 → 拆 6 表 → SQLite bi_demo.db（事务式事实快照）。

数据流：
  data/raw/sales_rank_raw.jsonl
       ↓  字段重命名 / 类型转换 / 空值处理 / 去重
  bi_demo.db（6 张表，Kimball 星型模型）
  ├── dim_brand      (数量随最新快照变化)
  ├── dim_series     (含 segment / endurance_km 口碑页补充)
  ├── dim_date       (YYYYMM 日期维度)
  ├── fact_sales_rank (销量事实；每次按完整 raw 快照事务重建)
  ├── fact_price      (报价快照)
  └── fact_review     (口碑评分)

运行：python data/clean_load.py
"""
import json
import re
import sqlite3
from pathlib import Path

RAW_FILE = Path(__file__).parent / "raw" / "sales_rank_raw.jsonl"
KOUBEI_FILE = Path(__file__).parent / "raw" / "koubei_series_detail.jsonl"
DB_FILE  = Path(__file__).parent.parent / "bi_demo.db"
POWERTRAIN_MAP = {1: "纯电", 2: "插混", 3: "增程"}
RANK_TYPE_SALES = 11
ETL_VERSION = "v1.0"


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
    value = float(score)
    # 历史 raw 保存 404，新版采集器可能已经保存 4.04；两种口径都兼容。
    if value > 10:
        value /= 100
    return round(value, 1)


def norm_text(text: str | None) -> str | None:
    """去首尾空白；纯空字符串 → None。"""
    if text is None:
        return None
    s = str(text).strip()
    return s if s else None


def infer_powertrain(energy_type: int) -> str:
    """懂车帝 new_energy_type 枚举 → 内部 powertrain 标签。"""
    return POWERTRAIN_MAP.get(energy_type, "新能源")


def load_koubei(path: Path = KOUBEI_FILE) -> dict[int, dict]:
    """读取口碑详情快照，按 ``series_id`` 以后出现的记录覆盖旧记录。"""
    if not path.exists():
        return {}

    result: dict[int, dict] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} 第 {line_number} 行不是合法 JSON") from exc
            series_id = row.get("series_id")
            if series_id is None:
                continue
            config = row.get("pc_config") or {}
            endurance_text = (
                row.get("recharge_mileage")
                or config.get("recharge_mileage")
            )
            result[int(series_id)] = {
                "segment": norm_text(row.get("car_type")),
                "endurance_km": (
                    row.get("endurance_km")
                    if row.get("endurance_km") is not None
                    else parse_endurance(endurance_text)
                ),
                "score": norm_score(row.get("total_score")),
            }
    return result


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
    raw_rows = [
        json.loads(line)
        for line in RAW_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # 历史 append 文件可能已有重复；与采集器使用同一业务主键，最后快照覆盖。
    rows_by_key = {}
    for row in raw_rows:
        key = (str(row["_month"]), int(row["_new_energy_type"]), row["series_id"])
        rows_by_key[key] = row
    rows = list(rows_by_key.values())
    print(f"共 {len(raw_rows)} 行原始记录，按业务主键去重后 {len(rows)} 行")

    conn = sqlite3.connect(DB_FILE)
    conn.executescript(DDL)

    brands, series, dates = {}, {}, {}
    koubei = load_koubei()

    for r in rows:
        # 维度去重收集
        brands[r["brand_id"]] = r["brand_name"]
        detail = koubei.get(int(r["series_id"]), {})
        guide_min = r.get("min_price")
        guide_max = r.get("max_price")
        parsed_min, parsed_max = parse_price_range(r.get("price"))
        series[r["series_id"]] = {
            "series_name": r["series_name"],
            "brand_id":    r["brand_id"],
            "powertrain":  infer_powertrain(r["_new_energy_type"]),
            "segment": detail.get("segment"),
            "endurance_km": detail.get("endurance_km"),
            "guide_price_min": guide_min if isinstance(guide_min, (int, float)) else parsed_min,
            "guide_price_max": guide_max if isinstance(guide_max, (int, float)) else parsed_max,
            "image_url": norm_text(r.get("image")),
        }
        date_id, year, month, quarter, ym = parse_month(r["_month"])
        dates[date_id] = {
            "year": year,
            "month": month,
            "quarter": quarter,
            "ym": ym,
        }

    # 写维度表
    conn.executemany(
        "INSERT INTO dim_brand(brand_id,brand_name) VALUES(?,?) "
        "ON CONFLICT(brand_id) DO UPDATE SET brand_name=excluded.brand_name",
        brands.items(),
    )
    conn.executemany(
        "INSERT INTO dim_series(series_id,series_name,brand_id,segment,powertrain,endurance_km,"
        "guide_price_min,guide_price_max,image_url) "
        "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(series_id) DO UPDATE SET "
        "series_name=excluded.series_name,brand_id=excluded.brand_id,"
        "segment=COALESCE(excluded.segment,dim_series.segment),"
        "powertrain=excluded.powertrain,"
        "endurance_km=COALESCE(excluded.endurance_km,dim_series.endurance_km),"
        "guide_price_min=excluded.guide_price_min,"
        "guide_price_max=excluded.guide_price_max,"
        "image_url=excluded.image_url",
        [
            (
                sid,
                value["series_name"],
                value["brand_id"],
                value["segment"],
                value["powertrain"],
                value["endurance_km"],
                value["guide_price_min"],
                value["guide_price_max"],
                value["image_url"],
            )
            for sid, value in series.items()
        ],
    )
    conn.executemany(
        "INSERT INTO dim_date(date_id,year,month,quarter,ym) VALUES(?,?,?,?,?) "
        "ON CONFLICT(date_id) DO UPDATE SET year=excluded.year,month=excluded.month,"
        "quarter=excluded.quarter,ym=excluded.ym",
        [
            (key, value["year"], value["month"], value["quarter"], value["ym"])
            for key, value in dates.items()
        ],
    )

    # crawler 会把历史分区与本次刷新分区原子合并成一个完整 JSONL 快照，因此这里
    # 在同一事务中重建事实表。只做 UPSERT 会留下上游榜单已移除的旧车系，正是此前
    # “相邻月份看起来完全相同/总行数比原始记录多”的污染来源。
    conn.execute("DELETE FROM fact_sales_rank")
    conn.execute("DELETE FROM fact_price")
    conn.execute("DELETE FROM fact_review")

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
            "INSERT INTO fact_price"
            "(series_id,date_id,guide_price_min,guide_price_max,price_text,dealer_price_text,has_dealer_price)"
            " VALUES(?,?,?,?,?,?,?)",
            (r["series_id"], date_id, pmin, pmax2 or pmax,
             r.get("price"), r.get("dealer_price"),
             1 if r.get("dealer_price") else 0))

        detail = koubei.get(int(r["series_id"]), {})
        conn.execute(
            "INSERT INTO fact_review(series_id,date_id,review_count,score) VALUES(?,?,?,?)",
            (
                r["series_id"],
                date_id,
                r.get("car_review_count") or 0,
                detail.get("score"),
            ),
        )

    conn.commit()

    # 验收统计
    for tbl in ("dim_brand", "dim_series", "dim_date", "fact_sales_rank", "fact_price", "fact_review"):
        cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {cnt} 行")

    conn.close()
    print(f"\n入库完成 → {DB_FILE}")


if __name__ == "__main__":
    run()
