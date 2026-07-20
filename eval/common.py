"""评测公共工具：LLM-as-judge（复用项目 DeepSeek）+ SQL 结果集等价比对 + 小工具。

为什么自实现 judge 而非全靠 RAGAS 库：RAGAS 新版 API 多变、中文 + 自定义 LLM(DeepSeek) 配置
有坑、且把 langchain 全家拖进 CI 偏重。这里按 RAGAS 的**原定义**用项目同款 LLM 实现四指标，
确定性指标(检索命中/结果集等价)则完全不依赖 LLM——可复现、可进 CI。RAGAS 真库另跑一版做交叉验证。
"""
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm import chat  # noqa: E402


# ============================================================ LLM judge 基础
def _judge_raw(system: str, user: str, temperature: float = 0.0) -> str:
    return chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=temperature)


def judge_json(system: str, user: str, default: dict) -> dict:
    """让 judge 只输出 JSON，解析失败回退 default。"""
    raw = _judge_raw(system, user)
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*|```$", "", s.strip()).strip()
    try:
        return json.loads(s)
    except Exception:
        i, j = s.find("{"), s.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(s[i:j + 1])
            except Exception:
                pass
    return dict(default)


# ============================================================ RAGAS 四指标（LLM-judge 实现）
_CTX = "\n\n".join  # 拼接 contexts


def context_precision(question: str, ground_truth: str, contexts: list) -> float:
    """检索到的每个 context 是否与「问题+标准答案」相关；相关项越靠前分越高（RAGAS 定义的 MAP@K）。"""
    if not contexts:
        return 0.0
    sys_p = ("你是检索质量评审。判断每个【片段】是否对回答【问题】有用（与标准答案相关即有用）。"
             "只输出 JSON：{\"useful\":[0或1,...]}，长度与片段数一致。")
    listing = "\n".join(f"[{i + 1}] {c[:400]}" for i, c in enumerate(contexts))
    user_p = f"问题：{question}\n标准答案：{ground_truth}\n片段：\n{listing}"
    r = judge_json(sys_p, user_p, {"useful": [0] * len(contexts)})
    flags = (r.get("useful") or [])[:len(contexts)]
    flags = [1 if int(x) == 1 else 0 for x in flags] + [0] * (len(contexts) - len(flags))
    # MAP@K：相关项命中位置的 precision 平均
    hit, acc, cum = 0, 0.0, 0
    for k, f in enumerate(flags, 1):
        if f:
            cum += 1
            acc += cum / k
            hit += 1
    return round(acc / hit, 4) if hit else 0.0


def context_recall(ground_truth: str, contexts: list) -> float:
    """标准答案里的每个事实点，能否在检索到的 contexts 中找到支持（RAGAS context recall）。"""
    if not contexts:
        return 0.0
    sys_p = ("把【标准答案】拆成若干事实点，判断每个点能否由【参考片段】支持。"
             "只输出 JSON：{\"total\":整数, \"supported\":整数}。")
    user_p = f"标准答案：{ground_truth}\n参考片段：\n{_CTX(c[:500] for c in contexts)}"
    r = judge_json(sys_p, user_p, {"total": 1, "supported": 0})
    t, s = max(int(r.get("total", 1)), 1), int(r.get("supported", 0))
    return round(min(s, t) / t, 4)


def faithfulness(answer: str, contexts: list) -> float:
    """生成答案的每个论断能否由 contexts 支持（防幻觉，RAGAS faithfulness）。"""
    if not answer or not contexts:
        return 0.0
    sys_p = ("把【答案】拆成若干论断，判断每个论断能否由【参考片段】推出（不能臆测）。"
             "只输出 JSON：{\"total\":整数, \"grounded\":整数}。")
    user_p = f"答案：{answer}\n参考片段：\n{_CTX(c[:500] for c in contexts)}"
    r = judge_json(sys_p, user_p, {"total": 1, "grounded": 0})
    t, g = max(int(r.get("total", 1)), 1), int(r.get("grounded", 0))
    return round(min(g, t) / t, 4)


def answer_relevancy(question: str, answer: str) -> float:
    """答案对问题的切题程度，0~1（RAGAS answer relevancy 的近似：直接打分）。"""
    if not answer:
        return 0.0
    sys_p = ("评估【答案】对【问题】的切题程度：完全切题=1.0，部分=0.5，跑题/答非所问=0。"
             "只输出 JSON：{\"score\":0~1 小数}。")
    r = judge_json(sys_p, f"问题：{question}\n答案：{answer}", {"score": 0.0})
    try:
        return round(max(0.0, min(1.0, float(r.get("score", 0.0)))), 4)
    except Exception:
        return 0.0


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
