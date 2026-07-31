"""Regression tests for Text2SQL evaluation.

Contract for result_set_equal:
- Row count must match.
- Column count per row must match.
- Column aliases (dict keys) are ignored.
- Values compared positionally (by dict insertion order = SQL SELECT order).
- Unordered: Counter of row tuples.
- Ordered: list equality of row tuples.
- Numeric normalization: int/float/numeric-string → 4-decimal canonical form.
"""
import pytest
from eval.common import result_set_equal, load_jsonl

DATASET_PATH = "eval/datasets/text2sql.jsonl"


# ── Gold SQL self-check ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def gold_data():
    return load_jsonl(DATASET_PATH)


@pytest.mark.integration
def test_gold_sql_all_executable(gold_data):
    from app.db import run_query
    from app.sql_guard import ensure_safe, with_limit
    errors = []
    for it in gold_data:
        try:
            run_query(with_limit(ensure_safe(it["gold_sql"])))
        except Exception as e:
            errors.append((it["id"], str(e)[:80]))
    assert errors == [], f"Gold SQL execution failures: {errors}"


@pytest.mark.integration
def test_gold_sql_all_nonempty(gold_data):
    """Both-empty must never inflate EX accuracy for an invalid evaluation item."""
    from app.db import run_query
    from app.sql_guard import ensure_safe, with_limit

    empty = []
    for it in gold_data:
        _, rows = run_query(with_limit(ensure_safe(it["gold_sql"])))
        if not rows:
            empty.append(it["id"])
    assert empty == [], f"Gold SQL returned no rows: {empty}"


@pytest.mark.integration
def test_gold_sql_no_direct_date_id_yyyymm(gold_data):
    import re
    bad = []
    for it in gold_data:
        if re.search(r"date_id\s*=\s*20\d{4}", it["gold_sql"]):
            bad.append(it["id"])
    assert bad == [], f"Gold SQL still uses YYYYMM date_id format: {bad}"


# ── Positional match: same column order, alias differs, values same ───────────

def test_same_order_different_alias_passes():
    gold = [{"v": 100}]
    pred = [{"total": 100}]
    assert result_set_equal(gold, pred)


def test_two_columns_same_order_passes():
    gold = [{"year": 2025, "sales": 100}]
    pred = [{"y": 2025, "s": 100}]
    assert result_set_equal(gold, pred)


# ── Column value swap must FAIL ───────────────────────────────────────────────

def test_year_sales_swap_fails():
    """Year and sales values swapped must fail (positional mismatch)."""
    gold = [{"year": 2025, "sales": 100}]
    pred = [{"year": 100, "sales": 2025}]
    assert not result_set_equal(gold, pred)


def test_two_column_value_swap_fails():
    gold = [{"a": 1, "b": 2}]
    pred = [{"x": 2, "y": 1}]
    assert not result_set_equal(gold, pred)


# ── Extra column fails ────────────────────────────────────────────────────────

def test_extra_column_fails():
    gold = [{"v": 128377}]
    pred = [{"series_name": "X", "total_volume": 128377}]
    assert not result_set_equal(gold, pred)


def test_case_14_pred_empty_fails():
    """sql-014 pattern: gold has value, pred has 0 rows."""
    gold = [{"v": 102744}]
    pred = []
    assert not result_set_equal(gold, pred)


# ── Row count mismatch ────────────────────────────────────────────────────────

def test_different_row_count_fails():
    gold = [{"v": 1}, {"v": 2}]
    pred = [{"v": 1}]
    assert not result_set_equal(gold, pred)


def test_both_empty_passes():
    assert result_set_equal([], [])


def test_empty_vs_nonempty_fails():
    assert not result_set_equal([], [{"v": 1}])
    assert not result_set_equal([{"v": 1}], [])


# ── Unordered: row order doesn't matter ───────────────────────────────────────

def test_unordered_row_swap_passes():
    gold = [{"a": 1, "b": 10}, {"a": 2, "b": 20}]
    pred = [{"x": 2, "y": 20}, {"x": 1, "y": 10}]
    assert result_set_equal(gold, pred, ordered=False)


def test_ordered_row_swap_fails():
    gold = [{"a": 1, "b": 10}, {"a": 2, "b": 20}]
    pred = [{"x": 2, "y": 20}, {"x": 1, "y": 10}]
    assert not result_set_equal(gold, pred, ordered=True)


def test_ordered_same_sequence_passes():
    gold = [{"a": 1}, {"a": 2}]
    pred = [{"b": 1}, {"b": 2}]
    assert result_set_equal(gold, pred, ordered=True)


# ── Multiset / duplicate rows ─────────────────────────────────────────────────

def test_multiset_duplicate_rows():
    gold = [{"v": 1}, {"v": 1}, {"v": 2}]
    pred = [{"v": 2}, {"v": 1}, {"v": 1}]
    assert result_set_equal(gold, pred)


def test_multiset_wrong_count_fails():
    gold = [{"v": 1}, {"v": 1}]
    pred = [{"v": 1}, {"v": 2}]
    assert not result_set_equal(gold, pred)


# ── Numeric normalization ─────────────────────────────────────────────────────

def test_numeric_string_normalization():
    gold = [{"v": 1.0}]
    pred = [{"v": "1.0000"}]
    assert result_set_equal(gold, pred)


def test_integer_float_equal():
    gold = [{"v": 42}]
    pred = [{"v": 42.0}]
    assert result_set_equal(gold, pred)


# ── NULL and zero ─────────────────────────────────────────────────────────────

def test_null_matches_null():
    gold = [{"v": None}]
    pred = [{"v": None}]
    assert result_set_equal(gold, pred)


def test_null_row_vs_empty_set():
    gold = [{"v": None}]
    pred = []
    assert not result_set_equal(gold, pred)


def test_zero_value():
    gold = [{"v": 0}]
    pred = [{"count": 0}]
    assert result_set_equal(gold, pred)


# ── Pivot vs group structure ──────────────────────────────────────────────────

def test_pivot_vs_group_fails():
    gold = [{"t": 1, "v": 100}, {"t": 2, "v": 200}]
    pred = [{"col1": 100, "col2": 200}]
    assert not result_set_equal(gold, pred)
