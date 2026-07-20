"""数据质量校验套件（等价 Great Expectations 的核心 expectations，零额外重依赖）。
对只读分析库 bi_demo.db 跑一组「期望」：行数 / 非空 / 值域 / 唯一性 / 外键完整性 / 业务口径。
任一不满足即 fail —— 可接 CI 阻断「脏数据流入」。

为何不用 Great Expectations 库：GE 体量大、拉 pandas 全家且配置繁琐；这里按其 expectation 语义自实现，
报告结构(expectation/success/detail)与 GE 对齐，便于将来平滑迁移。

用法：python eval/data_quality.py        产出 eval/reports/data_quality.json，全通过 exit 0、否则 exit 1。
"""
import json
import os
import sqlite3
import sys

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
    # 行数（clean_load 落库后的真实基线）
    for t, n in [("fact_sales_rank", 8072), ("fact_price", 8072), ("fact_review", 8072),
                 ("dim_series", 409), ("dim_brand", 101), ("dim_date", 29)]:
        s.expect_row_count(t, n)
    # 非空
    s.expect_not_null("fact_sales_rank", "series_id")
    s.expect_not_null("fact_sales_rank", "date_id")
    s.expect_not_null("fact_sales_rank", "volume")
    # 值域 / 口径
    s.expect_values_in_set("fact_sales_rank", "new_energy_type", [1, 2, 3])
    s.expect_min("fact_sales_rank", "volume", 0)
    s.expect_min("fact_sales_rank", "rank", 1)
    s.expect_values_in_set("dim_series", "powertrain", ["纯电", "插混", "增程"])
    s.expect_values_in_set("dim_date", "year", [2024, 2025, 2026])
    s.expect_between("fact_review", "score", 0, 5)     # 口碑评分范围（补采回填后已有值；DOMAIN 仍称恒NULL，建议后端更新）
    # 唯一性 + 外键
    s.expect_unique("fact_sales_rank", ["series_id", "date_id", "new_energy_type", "rank_type"])
    s.expect_fk("fact_sales_rank", "series_id", "dim_series", "series_id")
    s.expect_fk("fact_sales_rank", "date_id", "dim_date", "date_id")
    return s.results


def run():
    conn = sqlite3.connect(DB)
    try:
        return build_suite(conn)
    finally:
        conn.close()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    results = run()
    ok = sum(r["success"] for r in results)
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(REPORT_DIR, "data_quality.json"), "w", encoding="utf-8") as f:
        json.dump({"total": len(results), "passed": ok, "results": results}, f, ensure_ascii=False, indent=2)
    print(f"数据质量：{ok}/{len(results)} 通过")
    for r in results:
        if not r["success"]:
            print(f"  [FAIL] {r['expectation']} —— {r['detail']}")
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
