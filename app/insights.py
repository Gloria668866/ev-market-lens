"""洞察生成：把查询结果喂回 LLM，输出“结论 + 归因 + 建议”，
实现 JD 说的从『描述性』升级到『指导性』分析。支持流式。"""
from .llm import chat_stream

SYS = """你是商业分析顾问。根据用户问题和查询结果，给出：
1) 一句话结论；2) 简要归因/趋势解读；3) 1-2 条可执行建议。
只依据给定数据，不要编造数字。中文，简洁。"""


def stream_insight(question: str, cols, rows):
    yield from chat_stream([
        {"role": "system", "content": SYS},
        {"role": "user", "content": f"问题：{question}\n列：{cols}\n数据（前若干行）：{rows[:20]}"},
    ], temperature=0.3)
