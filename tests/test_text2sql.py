"""Text2SQL 提取与领域提示单测。"""
from app.text2sql import _extract_sql, DOMAIN


def test_extract_plain():
    assert _extract_sql("SELECT a FROM t").upper().startswith("SELECT")


def test_extract_codeblock():
    assert _extract_sql("```sql\nSELECT a FROM t\n```").upper().startswith("SELECT")


def test_extract_strips_semicolon():
    assert not _extract_sql("SELECT a FROM t;").endswith(";")


def test_extract_with_prose_prefix():
    out = _extract_sql("好的，SQL 如下：\nSELECT a FROM t WHERE x=1")
    assert out.upper().startswith("SELECT")


def test_domain_describes_star_schema():
    assert "fact_sales_rank" in DOMAIN and "new_energy_type" in DOMAIN
