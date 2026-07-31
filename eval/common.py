"""评测公共工具：确定性 SQL 结果集等价比对与 JSONL/报表工具。

RAG 的当前公开评测实现位于 ``eval/rag_eval.py``。项目没有把自定义
LLM 打分函数冒充 RAGAS 指标；答案级能力边界以生成报告为准。
"""
import json
from collections import Counter

# ============================================================ SQL 结果集等价比对
def _canon(v):
    """单元格规范化：数字按 4 位小数比，其它去空白转字符串。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return f"{round(float(v), 4):.4f}"
    s = str(v).strip()
    try:
        return f"{round(float(s.replace(',', '')), 4):.4f}"
    except ValueError:
        return s


def _row_key(row_values):
    return tuple(_canon(v) for v in row_values)


def result_set_equal(gold_rows: list, pred_rows: list, ordered: bool = False) -> bool:
    """执行结果集等价（等价 SQL 算对）：默认无序多重集相等；ordered=True 时按行序比。
    gold_rows / pred_rows 为 dict 行列表（db.run_query 输出）。
    行数和列数必须一致；列名可不同但每行值的多重集必须匹配。"""
    if not gold_rows and not pred_rows:
        return True
    if not gold_rows or not pred_rows:
        return False
    if len(gold_rows) != len(pred_rows):
        return False
    if len(list(gold_rows[0].values())) != len(list(pred_rows[0].values())):
        return False

    g = [_row_key(r.values()) for r in gold_rows]
    p = [_row_key(r.values()) for r in pred_rows]
    if ordered:
        return g == p
    return Counter(g) == Counter(p)


# ============================================================ 报表小工具
def pct(x, n):
    return f"{(100.0 * x / n):.1f}%" if n else "—"


def load_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("//"):
                out.append(json.loads(line))
    return out
