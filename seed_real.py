"""生成车市镜分析库（真实 schema：dim_brand/dim_series/dim_date/fact_sales_rank/fact_price/fact_review）
运行: python seed_real.py
"""
import random
from datetime import date, timedelta
from sqlalchemy import create_engine, text
from app.config import DATABASE_URL

random.seed(42)
engine = create_engine(DATABASE_URL, future=True)

BRANDS = [
    (1, "比亚迪"), (2, "特斯拉"), (3, "理想"), (4, "蔚来"), (5, "小鹏"),
    (6, "零跑"), (7, "哪吒"), (8, "问界"), (9, "极氪"), (10, "小米"),
    (11, "吉利"), (12, "长安"), (13, "奇瑞"), (14, "长城"), (15, "五菱"),
    (16, "广汽"), (17, "上汽"), (18, "北汽"), (19, "东风"), (20, "江淮"),
]

SERIES = [
    (1, "小米SU7", 10, "中大型车", 1, 700, 21.59, 29.99),
    (2, "比亚迪汉", 1, "中大型车", 1, 605, 17.98, 24.98),
    (3, "比亚迪宋PLUS", 1, "紧凑型SUV", 2, 110, 12.98, 16.98),
    (4, "比亚迪海鸥", 1, "微型车", 1, 405, 6.98, 8.98),
    (5, "比亚迪秦PLUS", 1, "紧凑型车", 2, 120, 7.98, 12.98),
    (6, "理想L6", 3, "中大型SUV", 3, 212, 24.98, 28.98),
    (7, "理想L7", 3, "中大型SUV", 3, 210, 30.18, 35.98),
    (8, "理想L9", 3, "大型SUV", 3, 215, 40.98, 43.98),
    (9, "特斯拉Model Y", 2, "中型SUV", 1, 554, 26.39, 36.39),
    (10, "特斯拉Model 3", 2, "中型车", 1, 606, 23.19, 33.19),
    (11, "蔚来ET5", 4, "中型车", 1, 560, 32.80, 38.60),
    (12, "蔚来ES6", 4, "中型SUV", 1, 490, 33.80, 39.60),
    (13, "小鹏G6", 5, "中型SUV", 1, 580, 20.99, 27.69),
    (14, "小鹏P7+", 5, "中型车", 1, 500, 18.68, 21.88),
    (15, "零跑C11", 6, "中型SUV", 1, 502, 14.88, 20.58),
    (16, "问界M7", 8, "中大型SUV", 3, 240, 24.98, 32.98),
    (17, "问界M9", 8, "大型SUV", 1, 630, 46.98, 56.98),
    (18, "极氪001", 9, "中大型车", 1, 741, 26.90, 32.90),
    (19, "极氪007", 9, "中型车", 1, 688, 20.99, 25.99),
    (20, "五菱宏光MINIEV", 15, "微型车", 1, 170, 3.28, 9.99),
    (21, "比亚迪元PLUS", 1, "紧凑型SUV", 1, 430, 13.58, 16.38),
    (22, "比亚迪海豚", 1, "小型车", 1, 401, 10.28, 12.98),
    (23, "吉利银河L7", 11, "紧凑型SUV", 2, 55, 12.57, 16.97),
    (24, "长安启源A07", 12, "中大型车", 3, 200, 13.59, 15.99),
    (25, "长城坦克500 Hi4-T", 14, "中大型SUV", 2, 110, 33.50, 33.50),
    (26, "埃安Y Plus", 16, "紧凑型SUV", 1, 500, 11.98, 15.18),
    (27, "腾势D9", 1, "中大型MPV", 2, 190, 33.58, 44.58),
    (28, "仰望U8", 1, "大型SUV", 3, 180, 109.80, 109.80),
    (29, "深蓝SL03", 12, "中型车", 3, 200, 13.99, 17.39),
    (30, "哪吒X", 7, "紧凑型SUV", 1, 401, 9.98, 13.68),
]

DDL = [
    "DROP TABLE IF EXISTS fact_review",
    "DROP TABLE IF EXISTS fact_price",
    "DROP TABLE IF EXISTS fact_sales_rank",
    "DROP TABLE IF EXISTS dim_date",
    "DROP TABLE IF EXISTS dim_series",
    "DROP TABLE IF EXISTS dim_brand",
    "CREATE TABLE dim_brand (brand_id INTEGER PRIMARY KEY, brand_name VARCHAR(64) NOT NULL, sub_brand_id INTEGER, sub_brand_name VARCHAR(64), country_type VARCHAR(16), is_new_force BOOLEAN, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE dim_series (series_id INTEGER PRIMARY KEY, series_name VARCHAR(128) NOT NULL, brand_id INTEGER, sub_brand_id INTEGER, segment VARCHAR(32), powertrain VARCHAR(32), endurance_km INTEGER, guide_price_min NUMERIC(8,2), guide_price_max NUMERIC(8,2), image_url VARCHAR(256), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE dim_date (date_id INTEGER PRIMARY KEY, year SMALLINT NOT NULL, month SMALLINT NOT NULL, quarter SMALLINT NOT NULL, ym CHAR(7) NOT NULL)",
    """CREATE TABLE fact_sales_rank (id INTEGER PRIMARY KEY AUTOINCREMENT, series_id INTEGER, date_id INTEGER,
        new_energy_type SMALLINT, rank_type SMALLINT, rank INTEGER, last_rank INTEGER,
        volume INTEGER, source VARCHAR(32) DEFAULT 'dongchedi', source_url VARCHAR(512),
        crawl_time TIMESTAMP, etl_version VARCHAR(16),
        UNIQUE (series_id, date_id, new_energy_type, rank_type))""",
    """CREATE TABLE fact_price (id INTEGER PRIMARY KEY AUTOINCREMENT, series_id INTEGER, date_id INTEGER,
        snapshot_date DATE, guide_price_min NUMERIC(8,2), guide_price_max NUMERIC(8,2),
        price_text VARCHAR(64), dealer_price_text VARCHAR(64),
        has_dealer_price BOOLEAN, descender_price NUMERIC(8,2),
        source VARCHAR(32) DEFAULT 'dongchedi', source_url VARCHAR(512),
        crawl_time TIMESTAMP, etl_version VARCHAR(16))""",
    """CREATE TABLE fact_review (id INTEGER PRIMARY KEY AUTOINCREMENT, series_id INTEGER, date_id INTEGER,
        snapshot_date DATE, review_count INTEGER, score NUMERIC(3,1),
        sentiment VARCHAR(8), source VARCHAR(32) DEFAULT 'dongchedi',
        source_url VARCHAR(512), crawl_time TIMESTAMP, etl_version VARCHAR(16))""",
]


def run():
    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))

        for bid, bname in BRANDS:
            conn.execute(text("INSERT INTO dim_brand(brand_id, brand_name) VALUES(:a,:b)"),
                         {"a": bid, "b": bname})

        for s in SERIES:
            conn.execute(text(
                "INSERT INTO dim_series(series_id, series_name, brand_id, segment, powertrain, endurance_km, guide_price_min, guide_price_max) "
                "VALUES(:a,:b,:c,:d,:e,:f,:g,:h)"),
                {"a": s[0], "b": s[1], "c": s[2], "d": s[3], "e": s[4], "f": s[5], "g": s[6], "h": s[7]})

        dates = []
        did = 1
        for y in (2024, 2025, 2026):
            for m in range(1, 13):
                if y == 2026 and m > 4:
                    continue
                ym_str = f"{y}-{m:02d}"
                dates.append((did, y, m, (m - 1) // 3 + 1, ym_str))
                did += 1

        for d in dates:
            conn.execute(text("INSERT INTO dim_date(date_id, year, month, quarter, ym) VALUES(:a,:b,:c,:d,:e)"),
                         {"a": d[0], "b": d[1], "c": d[2], "d": d[3], "e": d[4]})

        powertrain_map = {1: "纯电", 2: "插混", 3: "增程"}
        base_volumes = {}
        for s in SERIES:
            base_volumes[s[0]] = {
                1: random.randint(2000, 20000),
                2: random.randint(500, 8000),
                3: random.randint(500, 6000),
            }

        sid = 1
        price_id = 1
        review_id = 1
        for d in dates:
            for s in SERIES:
                pt_val = s[4]
                vol = max(0, base_volumes[s[0]][pt_val] + random.randint(-2000, 2000))
                rank = random.randint(1, 30)
                last_rank_val = random.randint(1, 30) if random.random() > 0.2 else None
                conn.execute(text(
                    "INSERT INTO fact_sales_rank(id, series_id, date_id, new_energy_type, rank_type, rank, last_rank, volume) "
                    "VALUES(:id,:sid,:did,:ne,:rt,:rk,:lr,:vol)"),
                    {"id": sid, "sid": s[0], "did": d[0], "ne": pt_val, "rt": 0,
                     "rk": rank, "lr": last_rank_val, "vol": vol})
                sid += 1

                if random.random() < 0.3:
                    conn.execute(text(
                        "INSERT INTO fact_price(id, series_id, date_id, snapshot_date, guide_price_min, guide_price_max, price_text, descender_price) "
                        "VALUES(:id,:sid,:did,:sd,:gmin,:gmax,:pt,:dp)"),
                        {"id": price_id, "sid": s[0], "did": d[0], "sd": f"{d[3]}-{d[2]:02d}-01",
                         "gmin": s[6], "gmax": s[7],
                         "pt": f"{s[6]}-{s[7]}万",
                         "dp": round(random.uniform(0, 1.5), 2)})
                    price_id += 1

                if random.random() < 0.25:
                    score_val = round(random.uniform(3.5, 5.0), 1) if random.random() > 0.2 else None
                    conn.execute(text(
                        "INSERT INTO fact_review(id, series_id, date_id, snapshot_date, review_count, score) "
                        "VALUES(:id,:sid,:did,:sd,:rc,:sc)"),
                        {"id": review_id, "sid": s[0], "did": d[0], "sd": f"{d[3]}-{d[2]:02d}-01",
                         "rc": random.randint(50, 5000), "sc": score_val})
                    review_id += 1

    print(f"Seed data written: {len(BRANDS)} brands / {len(SERIES)} series / {len(dates)} months / {sid-1} sales rows / {price_id-1} price rows / {review_id-1} review rows")


if __name__ == "__main__":
    run()
