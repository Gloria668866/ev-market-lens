"""懂车帝销量榜增量采集。

默认补齐 2024-01 至上一个完整月之间缺失的「月份×能源类型」分区，并刷新
最近两个完整月。输出按 ``(_month, _new_energy_type, series_id)`` 去重后原子
替换，重复运行不会追加重复记录。

公开销量 JSON API 不需要浏览器，生产环境只使用 Python 标准库 HTTP。
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


API_URL = "https://www.dongchedi.com/motor/pc/car/rank_data"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    ),
    "Referer": "https://www.dongchedi.com/sales",
    "Accept": "application/json, text/plain, */*",
}
ENERGY_TYPES = (1, 2, 3)
ENERGY_LABELS = {1: "纯电", 2: "插混", 3: "增程"}
MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
PAGE_SIZE = 50
MAX_PAGES = 100
REQUEST_TIMEOUT_SECONDS = 20.0
MAX_RETRIES = 3
PAGE_DELAY_SECONDS = 0.25
DEFAULT_START_MONTH = "202401"
OUT_FILE = Path(__file__).parent / "raw" / "sales_rank_raw.jsonl"

Record = dict
Fetcher = Callable[[str, int], list[Record]]


def _validate_month(value: str) -> tuple[int, int]:
    """校验 YYYYMM，并返回 ``(year, month)``。"""
    if len(value) != 6 or not value.isdigit():
        raise ValueError(f"月份必须是 YYYYMM：{value!r}")
    year, month = int(value[:4]), int(value[4:])
    if year < 2000 or not 1 <= month <= 12:
        raise ValueError(f"非法月份：{value!r}")
    return year, month


def month_range(start: str, end: str) -> list[str]:
    """生成包含首尾的 YYYYMM 列表，支持跨年。"""
    year, month = _validate_month(start)
    end_year, end_month = _validate_month(end)
    if (year, month) > (end_year, end_month):
        raise ValueError(f"起始月份不能晚于结束月份：{start} > {end}")

    result: list[str] = []
    while (year, month) <= (end_year, end_month):
        result.append(f"{year}{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result


def market_date(now: datetime | None = None) -> date:
    """返回销量月度任务采用的中国市场自然日。"""
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("now 必须是带时区的 datetime")
    return instant.astimezone(MARKET_TIMEZONE).date()


def previous_complete_month(today: date | None = None) -> str:
    """返回给定日期之前最近一个完整自然月。"""
    current = today or market_date()
    previous_day = current.replace(day=1) - timedelta(days=1)
    return f"{previous_day.year}{previous_day.month:02d}"


def _record_key(row: Record) -> tuple[str, int, object]:
    try:
        month = str(row["_month"])
        energy_type = int(row["_new_energy_type"])
        series_id = row["series_id"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"销量记录缺少幂等键：{row!r}") from exc
    if series_id is None:
        raise ValueError(f"销量记录 series_id 为空：{row!r}")
    _validate_month(month)
    return month, energy_type, series_id


def _partition_key(row: Record) -> tuple[str, int]:
    month, energy_type, _ = _record_key(row)
    return month, energy_type


def _sort_key(row: Record) -> tuple:
    month, energy_type, series_id = _record_key(row)
    rank = row.get("rank")
    rank_key = rank if isinstance(rank, int) else 10**9
    return month, energy_type, rank_key, str(series_id)


def dedupe_records(rows: Iterable[Record]) -> list[Record]:
    """按采集主键去重；同键以后出现的记录覆盖旧记录。"""
    latest: dict[tuple[str, int, object], Record] = {}
    for row in rows:
        latest[_record_key(row)] = dict(row)
    return sorted(latest.values(), key=_sort_key)


def read_records(path: Path = OUT_FILE) -> list[Record]:
    """读取现有 JSONL；坏行直接失败，避免随后原子替换掉可恢复数据。"""
    if not path.exists():
        return []

    rows: list[Record] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} 第 {line_number} 行不是合法 JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path} 第 {line_number} 行不是 JSON 对象")
            _record_key(row)
            rows.append(row)
    return rows


def plan_batches(
    existing_rows: Iterable[Record],
    start: str,
    end: str,
    *,
    energy_types: Sequence[int] = ENERGY_TYPES,
    refresh_months: int = 2,
) -> list[tuple[str, int]]:
    """计算需要采集的分区：历史缺失分区 + 范围内最近 N 个月。"""
    months = month_range(start, end)
    if refresh_months < 0:
        raise ValueError("refresh_months 不能为负数")

    existing_partitions = {_partition_key(row) for row in existing_rows}
    refresh_set = set(months[-refresh_months:]) if refresh_months else set()
    return [
        (month, int(energy_type))
        for month in months
        for energy_type in energy_types
        if (month, int(energy_type)) not in existing_partitions or month in refresh_set
    ]


def _request_json(
    url: str,
    *,
    opener=None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
    retries: int = MAX_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """用标准库请求 JSON，带超时和有限指数退避。"""
    if retries < 1:
        raise ValueError("retries 至少为 1")
    open_url = opener or urlopen
    last_error: Exception | None = None

    for attempt in range(retries):
        response = None
        try:
            response = open_url(Request(url, headers=HEADERS), timeout=timeout)
            body = response.read()
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("API 返回的顶层 JSON 不是对象")
            return payload
        except Exception as exc:  # 网络、超时、HTTP、解码和协议错误均有限重试
            last_error = exc
            if attempt + 1 < retries:
                sleep(float(2**attempt))
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()

    raise RuntimeError(f"请求懂车帝 API 失败，已重试 {retries} 次：{url}") from last_error


def latest_published_month(payload: dict) -> str:
    """Return the latest real YYYYMM advertised by the ranking API.

    Dongchedi silently falls back to the newest published ranking when callers
    request a future/unpublished month.  The returned rows do not carry their
    own month, so accepting them would relabel (for example) June rows as July.
    ``data.sells_rank_month`` is therefore part of our source contract.
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("API 响应缺少 data 对象")
    options = data.get("sells_rank_month")
    if not isinstance(options, list):
        raise RuntimeError("API 响应缺少 sells_rank_month，无法验证数据月份")

    months: list[str] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        value = str(option.get("month", ""))
        # The API also exposes aggregate selectors 500/1000; only YYYYMM is a
        # published natural month.
        if len(value) != 6 or not value.isdigit():
            continue
        try:
            _validate_month(value)
        except ValueError:
            continue
        months.append(value)
    if not months:
        raise RuntimeError("sells_rank_month 未包含合法 YYYYMM，拒绝写入")
    return max(months)


def fetch_month(
    month: str,
    energy_type: int,
    *,
    opener=None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
    retries: int = MAX_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
    page_delay: float = PAGE_DELAY_SECONDS,
) -> list[Record]:
    """采集一个月、一个能源类型的所有分页。"""
    _validate_month(month)
    if energy_type not in ENERGY_TYPES:
        raise ValueError(f"不支持的能源类型：{energy_type}")

    records: list[Record] = []
    offset = 0
    for page_number in range(MAX_PAGES):
        params = {
            "aid": 1839,
            "app_name": "auto_web_pc",
            "rank_data_type": 11,
            "new_energy_type": energy_type,
            "month": month,
            "count": PAGE_SIZE,
            "offset": offset,
        }
        url = f"{API_URL}?{urlencode(params)}"
        payload = _request_json(
            url,
            opener=opener,
            timeout=timeout,
            retries=retries,
            sleep=sleep,
        )
        published_through = latest_published_month(payload)
        if month > published_through:
            # Non-empty rows in this situation are the API's silent fallback
            # to ``published_through``.  Treat the partition as unpublished so
            # run() preserves any existing snapshot and retries in a later run.
            return []
        data = payload.get("data")
        items = data.get("list") or []
        if not isinstance(items, list):
            raise RuntimeError(f"API 响应 data.list 不是数组：{url}")
        if not items:
            break

        crawl_time = datetime.now(timezone.utc).isoformat()
        for item in items:
            if not isinstance(item, dict) or item.get("series_id") is None:
                continue
            record = dict(item)
            record.update(
                {
                    "_month": month,
                    "_new_energy_type": energy_type,
                    "_energy_label": ENERGY_LABELS[energy_type],
                    "_source": "dongchedi",
                    "_source_url": url,
                    "_crawl_time": crawl_time,
                }
            )
            records.append(record)

        if len(items) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        if page_delay:
            sleep(page_delay)
    else:
        raise RuntimeError(
            f"分页超过安全上限 {MAX_PAGES}：month={month}, energy_type={energy_type}"
        )

    return dedupe_records(records)


def atomic_write_records(path: Path, rows: Iterable[Record]) -> None:
    """在目标文件同目录写临时文件，fsync 后用 ``os.replace`` 原子替换。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def run(
    start: str | None = None,
    end: str | None = None,
    *,
    out_file: Path = OUT_FILE,
    fetcher: Fetcher = fetch_month,
    energy_types: Sequence[int] = ENERGY_TYPES,
    refresh_months: int = 2,
    today: date | None = None,
) -> dict:
    """执行增量采集并返回可测试的摘要。"""
    effective_start = start or DEFAULT_START_MONTH
    effective_end = end or previous_complete_month(today)
    month_range(effective_start, effective_end)  # 统一校验

    existing = read_records(out_file)
    batches = plan_batches(
        existing,
        effective_start,
        effective_end,
        energy_types=energy_types,
        refresh_months=refresh_months,
    )
    print(
        f"计划采集：{len(batches)} 个分区；范围 "
        f"{effective_start}~{effective_end}，最近 {refresh_months} 个月强制刷新"
    )

    fetched: list[Record] = []
    replaced_partitions: set[tuple[str, int]] = set()
    for month, energy_type in batches:
        rows = fetcher(month, energy_type)
        normalized: list[Record] = []
        for row in rows:
            normalized_row = dict(row)
            normalized_row["_month"] = month
            normalized_row["_new_energy_type"] = energy_type
            normalized.append(normalized_row)
        normalized = dedupe_records(normalized)

        label = ENERGY_LABELS.get(energy_type, str(energy_type))
        if normalized:
            fetched.extend(normalized)
            replaced_partitions.add((month, energy_type))
            print(f"  {month} {label}: {len(normalized)} 条")
        else:
            # API 暂未发布数据时保留旧快照；缺失分区会在下次继续补。
            print(f"  {month} {label}: 尚未发布或 0 条，保留旧分区并等待下次重试")

    preserved = [
        row for row in existing if _partition_key(row) not in replaced_partitions
    ]
    final_rows = dedupe_records([*preserved, *fetched])
    atomic_write_records(out_file, final_rows)

    summary = {
        "start": effective_start,
        "end": effective_end,
        "planned_batches": batches,
        "refreshed_partitions": sorted(replaced_partitions),
        "fetched_rows": len(dedupe_records(fetched)),
        "total_rows": len(final_rows),
        "output": str(out_file),
    }
    print(f"完成：{summary['total_rows']} 条幂等记录 → {out_file}")
    return summary


def main(argv: Sequence[str] | None = None) -> dict:
    """可由 CLI、Celery 或测试调用的入口。"""
    parser = argparse.ArgumentParser(description="懂车帝销量榜增量采集")
    parser.add_argument(
        "--start",
        default=None,
        help=f"起始月份 YYYYMM（默认 {DEFAULT_START_MONTH}）",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="结束月份 YYYYMM（默认上一个完整自然月）",
    )
    args = parser.parse_args(argv)
    try:
        return run(args.start, args.end)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
