"""清洗纯函数单测（T4 关键路径）：价格/月份/排名/续航/评分/文本规整。"""
import pytest

cl = pytest.importorskip("clean_load")  # data/clean_load.py（conftest 已把 data/ 加入 path）


def test_parse_price_range():
    assert cl.parse_price_range("5.98-8.98万") == (5.98, 8.98)
    assert cl.parse_price_range("7.99万") == (7.99, 7.99)   # 单值 min==max
    assert cl.parse_price_range("暂无报价") == (None, None)
    assert cl.parse_price_range(None) == (None, None)


def test_parse_month():
    assert cl.parse_month("202503") == (202503, 2025, 3, 1, "2025-03")
    assert cl.parse_month("202512")[3] == 4   # quarter
    assert cl.parse_month("202601")[1] == 2026


def test_clean_rank_new_entry():
    assert cl.clean_rank(0) == (None, True)
    assert cl.clean_rank(None) == (None, True)
    assert cl.clean_rank(5) == (5, False)


def test_parse_endurance():
    assert cl.parse_endurance("593-821km") == 821   # 区间取上限
    assert cl.parse_endurance("500km") == 500
    assert cl.parse_endurance("-") is None


def test_norm_score():
    assert cl.norm_score(404) == 4.0   # ×100 还原
    assert cl.norm_score(0) is None
    assert cl.norm_score(None) is None


def test_norm_text():
    assert cl.norm_text("  x ") == "x"
    assert cl.norm_text("   ") is None
