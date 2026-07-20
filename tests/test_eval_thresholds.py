"""评测阈值门禁（CI 阻断合并的关口，等价 DeepEval 的 assert）：
读最近一次评测产出的 JSON 报告，低于阈值即 fail；报告未生成则 skip（本地未跑评测时不挡）。
阈值取保守下限，作为「不允许回退到此线以下」的红线。"""
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "eval", "reports")

# 红线阈值（低于即阻断合并）
# 红线 = 实测之下的保守线（意图89% / Text2SQL 78% / RAG faith 0.80 / 拒答100%），低于即视为回退、阻断合并
TH_INTENT_ACC = 0.80
TH_T2S_EX = 0.70
TH_RAG_FAITH = 0.75
TH_RAG_ABSTAIN = 0.85


def _load(name):
    p = os.path.join(REPORTS, name)
    if not os.path.exists(p):
        pytest.skip(f"{name} 未生成（先跑对应评测脚本）")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _val(d, *keys):
    """逐层取值；任一层缺失或为 None → skip（报告不完整，不作为红线判定）。"""
    for k in keys:
        if not isinstance(d, dict) or d.get(k) is None:
            pytest.skip(f"指标 {'/'.join(keys)} 缺失（评测报告不完整，请跑全量）")
        d = d[k]
    return d


def test_intent_accuracy_gate():
    assert _val(_load("intent.json"), "accuracy") >= TH_INTENT_ACC


def test_text2sql_exec_accuracy_gate():
    assert _val(_load("text2sql.json"), "exec_accuracy") >= TH_T2S_EX


def test_rag_faithfulness_gate():
    assert _val(_load("rag.json"), "metrics_answerable", "faithfulness") >= TH_RAG_FAITH


def test_rag_hallucination_guard_gate():
    assert _val(_load("rag.json"), "hallucination_guard", "abstention_rate") >= TH_RAG_ABSTAIN
