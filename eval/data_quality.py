"""数据质量校验套件（等价 Great Expectations 的核心 expectations，零额外重依赖）。
对只读分析库 bi_demo.db 跑一组「期望」：行数 / 非空 / 值域 / 唯一性 / 外键完整性 / 业务口径。
任一不满足即 fail —— 可接 CI 阻断「脏数据流入」。

为何不用 Great Expectations 库：GE 体量大、拉 pandas 全家且配置繁琐；这里按其 expectation 语义自实现，
报告结构(expectation/success/detail)与 GE 对齐，便于将来平滑迁移。

用法：python eval/data_quality.py        产出 eval/reports/data_quality.json，全通过 exit 0、否则 exit 1。
"""
import json
import hashlib
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "bi_demo.db")
REPORT_DIR = os.path.join(ROOT, "eval", "reports")


class Suite:
    def __init__(self, conn):
        self.c = conn
        self.results = []

    def _add(self, name, ok, detail=""):
        self.results.append({"expectation": name, "success": bool(ok), "detail": detail})

    def _scalar(self, sql, params=()):
        return self.c.execute(sql, params).fetchone()[0]

    def expect_row_count(self, table, n):
        got = self._scalar(f"SELECT COUNT(*) FROM {table}")
        self._add(f"{table} 行数 == {n}", got == n, f"实际 {got}")

    def expect_min_row_count(self, table, n):
        got = self._scalar(f"SELECT COUNT(*) FROM {table}")
        self._add(f"{table} 行数 >= {n}", got >= n, f"实际 {got}")

    def expect_same_row_count(self, left, right):
        left_n = self._scalar(f"SELECT COUNT(*) FROM {left}")
        right_n = self._scalar(f"SELECT COUNT(*) FROM {right}")
        self._add(
            f"{left} 与 {right} 行数一致",
            left_n == right_n,
            f"{left_n} vs {right_n}",
        )

    def expect_not_null(self, table, col):
        bad = self._scalar(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL")
        self._add(f"{table}.{col} 无空值", bad == 0, f"{bad} 条空")

    def expect_values_in_set(self, table, col, allowed):
        ph = ",".join("?" * len(allowed))
        bad = self._scalar(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL AND {col} NOT IN ({ph})", allowed)
        self._add(f"{table}.{col} 取值 ⊆ {allowed}", bad == 0, f"{bad} 条越界")

    def expect_min(self, table, col, lo):
        bad = self._scalar(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL AND {col} < ?", (lo,))
        self._add(f"{table}.{col} >= {lo}", bad == 0, f"{bad} 条小于 {lo}")

    def expect_between(self, table, col, lo, hi):
        bad = self._scalar(
            f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL AND ({col} < ? OR {col} > ?)", (lo, hi))
        self._add(f"{table}.{col} ∈ [{lo},{hi}]", bad == 0, f"{bad} 条越界")

    def expect_unique(self, table, cols):
        key = ",".join(cols)
        dup = self._scalar(f"SELECT COUNT(*) FROM (SELECT {key} FROM {table} GROUP BY {key} HAVING COUNT(*)>1)")
        self._add(f"{table} ({key}) 唯一", dup == 0, f"{dup} 组重复")

    def expect_fk(self, table, col, ref, refcol):
        orphan = self._scalar(
            f"SELECT COUNT(*) FROM {table} t LEFT JOIN {ref} r ON t.{col}=r.{refcol} WHERE r.{refcol} IS NULL")
        self._add(f"{table}.{col} → {ref}.{refcol} 外键完整", orphan == 0, f"{orphan} 条孤儿")


def build_suite(conn):
    s = Suite(conn)
    # 数据每月都会增长，不能把某次快照的精确行数写成永久门槛。
    # 这里守住合理下限与三张事实快照的一致性。
    for table, minimum in (
        ("fact_sales_rank", 5000),
        ("fact_price", 5000),
        ("fact_review", 5000),
        ("dim_series", 300),
        ("dim_brand", 50),
        ("dim_date", 24),
    ):
        s.expect_min_row_count(table, minimum)
    s.expect_same_row_count("fact_sales_rank", "fact_price")
    s.expect_same_row_count("fact_sales_rank", "fact_review")
    # 非空
    s.expect_not_null("fact_sales_rank", "series_id")
    s.expect_not_null("fact_sales_rank", "date_id")
    s.expect_not_null("fact_sales_rank", "volume")
    # 值域 / 口径
    s.expect_values_in_set("fact_sales_rank", "new_energy_type", [1, 2, 3])
    s.expect_min("fact_sales_rank", "volume", 0)
    s.expect_min("fact_sales_rank", "rank", 1)
    s.expect_values_in_set("dim_series", "powertrain", ["纯电", "插混", "增程"])
    s.expect_between("dim_date", "year", 2024, datetime.now().year)
    s.expect_between("fact_review", "score", 0, 5)     # 口碑评分范围（补采回填后已有值；DOMAIN 仍称恒NULL，建议后端更新）
    # 唯一性 + 外键
    s.expect_unique("fact_sales_rank", ["series_id", "date_id", "new_energy_type", "rank_type"])
    s.expect_fk("fact_sales_rank", "series_id", "dim_series", "series_id")
    s.expect_fk("fact_sales_rank", "date_id", "dim_date", "date_id")

    # 日期覆盖应按自然月连续，且每个月都要有纯电/插混/增程三类分区。
    min_date, max_date, date_count = conn.execute(
        "SELECT MIN(date_id), MAX(date_id), COUNT(*) FROM dim_date"
    ).fetchone()
    if min_date and max_date:
        min_index = (min_date // 100) * 12 + (min_date % 100)
        max_index = (max_date // 100) * 12 + (max_date % 100)
        expected_months = max_index - min_index + 1
        s._add(
            "dim_date 从最早到最新月份连续",
            date_count == expected_months,
            f"{min_date}~{max_date}：实际 {date_count} 月，应为 {expected_months} 月",
        )
    missing_energy = s._scalar(
        "SELECT COUNT(*) FROM ("
        "SELECT date_id FROM fact_sales_rank "
        "GROUP BY date_id HAVING COUNT(DISTINCT new_energy_type) <> 3)"
    )
    s._add("每个月覆盖 3 种新能源类型", missing_energy == 0, f"{missing_energy} 个月缺分区")

    # 防止把一个月的快照误复制到下个月（此前真实发生过的数据污染）。
    latest_dates = [
        row[0]
        for row in conn.execute(
            "SELECT date_id FROM dim_date ORDER BY date_id DESC LIMIT 2"
        ).fetchall()
    ]
    if len(latest_dates) == 2:
        snapshots = []
        for date_id in latest_dates:
            snapshots.append(set(conn.execute(
                "SELECT series_id,new_energy_type,rank,volume "
                "FROM fact_sales_rank WHERE date_id=?",
                (date_id,),
            ).fetchall()))
        s._add(
            "最近两个月销量快照不完全相同",
            snapshots[0] != snapshots[1],
            f"{latest_dates[1]} vs {latest_dates[0]}",
        )
    return s.results


def run():
    conn = sqlite3.connect(DB)
    try:
        return build_suite(conn)
    finally:
        conn.close()


def _build_meta() -> dict:
    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": os.path.basename(DB),
    }
    try:
        meta["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
        meta["dirty_worktree"] = bool(subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            text=True,
        ).strip())
    except Exception:
        pass
    raw_path = os.path.join(ROOT, "data", "raw", "sales_rank_raw.jsonl")
    if os.path.exists(raw_path):
        with open(raw_path, "rb") as stream:
            meta["raw_sha256"] = hashlib.sha256(stream.read()).hexdigest()
    return meta


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    results = run()
    ok = sum(r["success"] for r in results)
    os.makedirs(REPORT_DIR, exist_ok=True)
    # Capture provenance before opening the tracked report for writing.
    # Opening with mode="w" truncates the file immediately and would otherwise
    # make an initially clean evaluation checkout report itself as dirty.
    payload = {
        "total": len(results),
        "passed": ok,
        "results": results,
        "_meta": _build_meta(),
    }
    with open(os.path.join(REPORT_DIR, "data_quality.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"数据质量：{ok}/{len(results)} 通过")
    for r in results:
        if not r["success"]:
            print(f"  [FAIL] {r['expectation']} —— {r['detail']}")
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
