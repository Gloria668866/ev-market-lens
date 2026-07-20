#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data/raw 的销量+口碑清洗后加载进【生产 PostgreSQL 分析库 bi】（dim_*/fact_*）。

用途：
  ① 初始导入：把 8072 行销量(+口碑回填)灌进生产 PG bi（替代 dev 的 SQLite bi_demo.db）。
  ② 月度刷新：Celery beat 月度采集后调它，把新数据 UPSERT 进 PG（幂等）。
复用 data/clean_load.py 的清洗函数（同口径），只把写库目标从 SQLite 换成 PostgreSQL。

连接：默认 postgresql://postgres:postgres@127.0.0.1:5432/bi（bi 库写入需 super，bi_readonly 只读）。
  生产用 ANALYSIS_PG_URL 覆盖（例：postgresql://postgres:强密码@127.0.0.1:5432/bi）。
运行：PYTHONUTF8=1 python deploy/load_analysis_pg.py
"""
import json, os, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg

from data.clean_load import (RAW_FILE, POWERTRAIN_MAP, RANK_TYPE_SALES, ETL_VERSION,
                             parse_month, parse_price_range, clean_rank, norm_text, load_koubei)

PG_URL = os.getenv("ANALYSIS_PG_URL", "postgresql://postgres:postgres@127.0.0.1:5432/bi")


def build():
    """读 raw + 口碑回填，构出维度/事实（逻辑与 clean_load 一致）。"""
    rows = [json.loads(l) for l in open(RAW_FILE, encoding="utf-8") if l.strip()]
    rows.sort(key=lambda r: r.get("_crawl_time", ""))
    koubei = load_koubei()
    dim_brand, dim_series, dim_date = {}, {}, {}
    fact_sales, fact_price, fact_review = [], [], []
    for r in rows:
        date_id, year, month, quarter, ym = parse_month(r["_month"])
        dim_date[date_id] = (date_id, year, month, quarter, ym)
        net = r.get("_new_energy_type"); powertrain = POWERTRAIN_MAP.get(net)
        bid = r.get("brand_id")
        if bid is not None:
            dim_brand[bid] = (bid, norm_text(r.get("brand_name")) or "未知品牌",
                              r.get("sub_brand_id"), norm_text(r.get("sub_brand_name")), None, None)
        sid = r["series_id"]; kb = koubei.get(sid, {})
        gmin, gmax = r.get("min_price"), r.get("max_price")
        if gmin is None or gmax is None:
            pmin, pmax = parse_price_range(r.get("price"))
            gmin = gmin if gmin is not None else pmin
            gmax = gmax if gmax is not None else pmax
        dim_series[sid] = (sid, norm_text(r.get("series_name")) or f"series_{sid}", bid,
                           r.get("sub_brand_id"), kb.get("segment"), powertrain,
                           kb.get("endurance_km"), gmin, gmax, norm_text(r.get("image")))
        vol = r.get("count")
        if not isinstance(vol, int) or vol <= 0:
            continue
        last_rank_clean, _ = clean_rank(r.get("last_rank"))
        snap = f"{ym}-01"
        fact_sales.append((sid, date_id, net, RANK_TYPE_SALES, r.get("rank"), last_rank_clean,
                           vol, r.get("_source", "dongchedi"), r.get("_source_url"), r.get("_crawl_time"), ETL_VERSION))
        gpmin, gpmax = parse_price_range(r.get("price"))
        dtext = r.get("descender_price"); dmin, _ = parse_price_range(dtext)
        fact_price.append((sid, date_id, snap, r.get("min_price") if r.get("min_price") is not None else gpmin,
                           r.get("max_price") if r.get("max_price") is not None else gpmax,
                           norm_text(r.get("price")), dtext if dmin is not None else None,
                           bool(r.get("has_dealer_price")), r.get("descender_price"),
                           r.get("_source", "dongchedi"), r.get("_source_url"), r.get("_crawl_time"), ETL_VERSION))
        fact_review.append((sid, date_id, snap, r.get("car_review_count"), kb.get("score"), None,
                            r.get("_source", "dongchedi"), r.get("_source_url"), r.get("_crawl_time"), ETL_VERSION))
    return dim_brand, dim_series, dim_date, fact_sales, fact_price, fact_review


def main():
    db, ds, dd, fs, fp, fr = build()
    print(f"构建：brand={len(db)} series={len(ds)} date={len(dd)} sales={len(fs)}")
    with psycopg.connect(PG_URL) as c:
        cur = c.cursor()
        cur.executemany("INSERT INTO dim_date(date_id,year,month,quarter,ym) VALUES(%s,%s,%s,%s,%s) "
                        "ON CONFLICT(date_id) DO UPDATE SET year=excluded.year,month=excluded.month,"
                        "quarter=excluded.quarter,ym=excluded.ym", list(dd.values()))
        cur.executemany("INSERT INTO dim_brand(brand_id,brand_name,sub_brand_id,sub_brand_name,country_type,is_new_force) "
                        "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(brand_id) DO UPDATE SET brand_name=excluded.brand_name,"
                        "sub_brand_id=excluded.sub_brand_id,sub_brand_name=excluded.sub_brand_name", list(db.values()))
        cur.executemany("INSERT INTO dim_series(series_id,series_name,brand_id,sub_brand_id,segment,powertrain,"
                        "endurance_km,guide_price_min,guide_price_max,image_url) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT(series_id) DO UPDATE SET series_name=excluded.series_name,brand_id=excluded.brand_id,"
                        "segment=excluded.segment,powertrain=excluded.powertrain,endurance_km=excluded.endurance_km,"
                        "guide_price_min=excluded.guide_price_min,guide_price_max=excluded.guide_price_max,"
                        "image_url=excluded.image_url", list(ds.values()))
        cur.executemany("INSERT INTO fact_sales_rank(series_id,date_id,new_energy_type,rank_type,rank,last_rank,volume,"
                        "source,source_url,crawl_time,etl_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT(series_id,date_id,new_energy_type,rank_type) DO UPDATE SET rank=excluded.rank,"
                        "last_rank=excluded.last_rank,volume=excluded.volume,crawl_time=excluded.crawl_time", fs)
        cur.executemany("INSERT INTO fact_price(series_id,date_id,snapshot_date,guide_price_min,guide_price_max,"
                        "price_text,dealer_price_text,has_dealer_price,descender_price,source,source_url,crawl_time,etl_version) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(series_id,date_id) DO UPDATE SET "
                        "guide_price_min=excluded.guide_price_min,guide_price_max=excluded.guide_price_max,"
                        "price_text=excluded.price_text,crawl_time=excluded.crawl_time", fp)
        cur.executemany("INSERT INTO fact_review(series_id,date_id,snapshot_date,review_count,score,sentiment,"
                        "source,source_url,crawl_time,etl_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT(series_id,date_id) DO UPDATE SET review_count=excluded.review_count,"
                        "score=excluded.score,crawl_time=excluded.crawl_time", fr)
        c.commit()
        for t in ("dim_brand", "dim_series", "dim_date", "fact_sales_rank", "fact_price", "fact_review"):
            print(f"  PG {t:18s} = {cur.execute(f'SELECT count(*) FROM {t}').fetchone()[0]}")
    print("✅ 分析库已加载进 PostgreSQL bi。")


if __name__ == "__main__":
    main()
