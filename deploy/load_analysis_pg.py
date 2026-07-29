#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把销量和口碑快照幂等加载到生产 PostgreSQL 分析库。"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

from data.clean_load import (
    ETL_VERSION,
    KOUBEI_FILE,
    POWERTRAIN_MAP,
    RANK_TYPE_SALES,
    RAW_FILE,
    clean_rank,
    load_koubei,
    norm_text,
    parse_month,
    parse_price_range,
)


PG_URL = os.getenv(
    "ANALYSIS_PG_URL",
    "postgresql://postgres:postgres@127.0.0.1:5432/bi",
)
MIN_SALES_ROWS = max(int(os.getenv("ANALYSIS_MIN_SALES_ROWS", "1")), 1)
MIN_SALES_MONTHS = max(int(os.getenv("ANALYSIS_MIN_SALES_MONTHS", "1")), 1)

FACT_PRICE_COLUMNS = (
    "series_id",
    "date_id",
    "snapshot_date",
    "guide_price_min",
    "guide_price_max",
    "price_text",
    "dealer_price_text",
    "has_dealer_price",
    "descender_price",
    "source",
    "source_url",
    "crawl_time",
    "etl_version",
)
FACT_REVIEW_COLUMNS = (
    "series_id",
    "date_id",
    "snapshot_date",
    "review_count",
    "score",
    "sentiment",
    "source",
    "source_url",
    "crawl_time",
    "etl_version",
)
_SNAPSHOT_TABLES = {"fact_price", "fact_review"}
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _raw_key(row: dict) -> tuple[str, int, object]:
    return (
        str(row["_month"]),
        int(row["_new_energy_type"]),
        row["series_id"],
    )


def _read_latest_rows(raw_file: Path) -> list[dict]:
    """读取并按采集业务键去重；时间更新者优先，同时间以后出现者优先。"""
    latest: dict[tuple[str, int, object], dict] = {}
    with raw_file.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{raw_file} 第 {line_number} 行不是合法 JSON") from exc
            key = _raw_key(row)
            previous = latest.get(key)
            if previous is None or str(row.get("_crawl_time") or "") >= str(
                previous.get("_crawl_time") or ""
            ):
                latest[key] = row
    return sorted(
        latest.values(),
        key=lambda row: (
            str(row["_month"]),
            int(row["_new_energy_type"]),
            str(row["series_id"]),
        ),
    )


def _number(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    low, _ = parse_price_range(str(value))
    return low


def build(
    *,
    raw_file: Path = RAW_FILE,
    koubei: dict[int, dict] | None = None,
):
    """构造与 PG schema 对齐的维度和事实行。"""
    if not raw_file.exists():
        raise FileNotFoundError(f"原始销量文件不存在：{raw_file}")

    rows = _read_latest_rows(raw_file)
    if not rows:
        raise ValueError("销量原始快照为空；拒绝刷新，避免清空线上事实表")
    if koubei is None:
        if not KOUBEI_FILE.exists():
            raise FileNotFoundError(
                f"口碑快照不存在：{KOUBEI_FILE}；拒绝刷新，避免把评分覆盖为空"
            )
        detail_by_series = load_koubei()
        if not detail_by_series:
            raise ValueError("口碑快照为空；拒绝刷新，避免把评分覆盖为空")
    else:
        detail_by_series = koubei

    dim_brand: dict[int, tuple] = {}
    dim_series: dict[int, tuple] = {}
    dim_date: dict[int, tuple] = {}
    fact_sales: dict[tuple, tuple] = {}
    fact_price: dict[tuple, tuple] = {}
    fact_review: dict[tuple, tuple] = {}

    for row in rows:
        date_id, year, month, quarter, ym = parse_month(str(row["_month"]))
        dim_date[date_id] = (date_id, year, month, quarter, ym)

        energy_type = int(row["_new_energy_type"])
        powertrain = POWERTRAIN_MAP.get(energy_type, "新能源")
        brand_id = row.get("brand_id")
        if brand_id is not None:
            dim_brand[int(brand_id)] = (
                int(brand_id),
                norm_text(row.get("brand_name")) or "未知品牌",
                row.get("sub_brand_id"),
                norm_text(row.get("sub_brand_name")),
                None,
                None,
            )

        series_id = int(row["series_id"])
        detail = detail_by_series.get(series_id, {})
        guide_min = _number(row.get("min_price"))
        guide_max = _number(row.get("max_price"))
        parsed_min, parsed_max = parse_price_range(row.get("price"))
        guide_min = guide_min if guide_min is not None else parsed_min
        guide_max = guide_max if guide_max is not None else parsed_max
        dim_series[series_id] = (
            series_id,
            norm_text(row.get("series_name")) or f"series_{series_id}",
            int(brand_id) if brand_id is not None else None,
            row.get("sub_brand_id"),
            detail.get("segment"),
            powertrain,
            detail.get("endurance_km"),
            guide_min,
            guide_max,
            norm_text(row.get("image")),
        )

        volume = row.get("count")
        if not isinstance(volume, int) or isinstance(volume, bool) or volume <= 0:
            continue

        last_rank, _ = clean_rank(row.get("last_rank"))
        source = norm_text(row.get("_source")) or "dongchedi"
        source_url = norm_text(row.get("_source_url"))
        crawl_time = norm_text(row.get("_crawl_time"))
        snapshot_date = f"{ym}-01"

        sales_key = (series_id, date_id, energy_type, RANK_TYPE_SALES)
        fact_sales[sales_key] = (
            series_id,
            date_id,
            energy_type,
            RANK_TYPE_SALES,
            row.get("rank"),
            last_rank,
            volume,
            source,
            source_url,
            crawl_time,
            ETL_VERSION,
        )

        snapshot_key = (series_id, date_id)
        dealer_price = norm_text(row.get("dealer_price"))
        has_dealer_price = row.get("has_dealer_price")
        if has_dealer_price is None:
            has_dealer_price = bool(dealer_price)
        fact_price[snapshot_key] = (
            series_id,
            date_id,
            snapshot_date,
            guide_min,
            guide_max,
            norm_text(row.get("price")),
            dealer_price,
            bool(has_dealer_price),
            _number(row.get("descender_price")),
            source,
            source_url,
            crawl_time,
            ETL_VERSION,
        )
        fact_review[snapshot_key] = (
            series_id,
            date_id,
            snapshot_date,
            row.get("car_review_count"),
            detail.get("score"),
            None,
            source,
            source_url,
            crawl_time,
            ETL_VERSION,
        )

    payload = (
        dim_brand,
        dim_series,
        dim_date,
        list(fact_sales.values()),
        list(fact_price.values()),
        list(fact_review.values()),
    )
    validate_payload(payload)
    return payload


def validate_payload(
    payload,
    *,
    min_sales_rows: int = MIN_SALES_ROWS,
    min_sales_months: int = MIN_SALES_MONTHS,
) -> None:
    """在任何 DELETE 前验证新快照，损坏/局部快照必须 fail-closed。"""
    _brands, series, dates, sales, prices, reviews = payload
    if len(sales) < min_sales_rows:
        raise ValueError(
            f"销量事实仅 {len(sales)} 行，低于安全下限 {min_sales_rows}；拒绝替换"
        )
    sales_months = {int(row[1]) for row in sales}
    if len(sales_months) < min_sales_months:
        raise ValueError(
            f"销量事实仅 {len(sales_months)} 个月，低于安全下限 "
            f"{min_sales_months}；拒绝替换"
        )
    if not series or not dates or not prices or not reviews:
        raise ValueError("分析快照的维度或价格/口碑事实为空；拒绝替换")


def replace_snapshot_rows(
    cursor,
    *,
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence],
) -> None:
    """替换无唯一约束的快照事实，保证重复加载不增加行数。"""
    if table not in _SNAPSHOT_TABLES:
        raise ValueError(f"不允许替换的表：{table}")
    if len(columns) < 2 or columns[0:2] != ("series_id", "date_id"):
        raise ValueError("快照事实前两列必须是 series_id、date_id")
    if not all(_IDENTIFIER.fullmatch(column) for column in columns):
        raise ValueError("列名包含非法标识符")

    latest: dict[tuple[object, object], tuple] = {}
    for row in rows:
        value = tuple(row)
        if len(value) != len(columns):
            raise ValueError(f"{table} 行长度与列定义不一致")
        latest[(value[0], value[1])] = value
    if not latest:
        return

    cursor.executemany(
        f"DELETE FROM {table} WHERE series_id=%s AND date_id=%s",
        list(latest),
    )
    placeholders = ",".join(["%s"] * len(columns))
    cursor.executemany(
        f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})",
        list(latest.values()),
    )


def load_connection(connection, payload) -> None:
    """事务内把完整 raw 快照同步进 PG，事实表以当前快照为准。"""
    validate_payload(payload)
    brands, series, dates, sales, prices, reviews = payload
    cursor = connection.cursor()

    cursor.executemany(
        "INSERT INTO dim_date(date_id,year,month,quarter,ym) "
        "VALUES(%s,%s,%s,%s,%s) ON CONFLICT(date_id) DO UPDATE SET "
        "year=excluded.year,month=excluded.month,quarter=excluded.quarter,ym=excluded.ym",
        list(dates.values()),
    )
    cursor.executemany(
        "INSERT INTO dim_brand(brand_id,brand_name,sub_brand_id,sub_brand_name,"
        "country_type,is_new_force) VALUES(%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT(brand_id) DO UPDATE SET "
        "brand_name=excluded.brand_name,sub_brand_id=excluded.sub_brand_id,"
        "sub_brand_name=excluded.sub_brand_name",
        list(brands.values()),
    )
    cursor.executemany(
        "INSERT INTO dim_series(series_id,series_name,brand_id,sub_brand_id,segment,"
        "powertrain,endurance_km,guide_price_min,guide_price_max,image_url) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT(series_id) DO UPDATE SET "
        "series_name=excluded.series_name,brand_id=excluded.brand_id,"
        "sub_brand_id=excluded.sub_brand_id,"
        "segment=COALESCE(excluded.segment,dim_series.segment),"
        "powertrain=excluded.powertrain,"
        "endurance_km=COALESCE(excluded.endurance_km,dim_series.endurance_km),"
        "guide_price_min=excluded.guide_price_min,"
        "guide_price_max=excluded.guide_price_max,image_url=excluded.image_url",
        list(series.values()),
    )
    # raw JSONL 是完整权威快照。事务内整表替换可清除已从榜单消失的事实键；
    # PostgreSQL MVCC 会让并发读者在提交前继续看到旧快照，不暴露中间空表。
    for table in ("fact_sales_rank", "fact_price", "fact_review"):
        cursor.execute(f"DELETE FROM {table}")
    cursor.executemany(
        "INSERT INTO fact_sales_rank(series_id,date_id,new_energy_type,rank_type,rank,"
        "last_rank,volume,source,source_url,crawl_time,etl_version) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT(series_id,date_id,new_energy_type,rank_type) DO UPDATE SET "
        "rank=excluded.rank,last_rank=excluded.last_rank,volume=excluded.volume,"
        "source=excluded.source,source_url=excluded.source_url,"
        "crawl_time=excluded.crawl_time,etl_version=excluded.etl_version",
        sales,
    )
    replace_snapshot_rows(
        cursor,
        table="fact_price",
        columns=FACT_PRICE_COLUMNS,
        rows=prices,
    )
    replace_snapshot_rows(
        cursor,
        table="fact_review",
        columns=FACT_REVIEW_COLUMNS,
        rows=reviews,
    )
    connection.commit()


def main() -> None:
    payload = build()
    brands, series, dates, sales, prices, reviews = payload
    print(
        "构建："
        f"brand={len(brands)} series={len(series)} date={len(dates)} "
        f"sales={len(sales)} price={len(prices)} review={len(reviews)}"
    )
    with psycopg.connect(PG_URL) as connection:
        load_connection(connection, payload)
        cursor = connection.cursor()
        for table in (
            "dim_brand",
            "dim_series",
            "dim_date",
            "fact_sales_rank",
            "fact_price",
            "fact_review",
        ):
            count = cursor.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            print(f"  PG {table:18s} = {count}")
    print("✅ 分析库已加载进 PostgreSQL bi。")


if __name__ == "__main__":
    main()
