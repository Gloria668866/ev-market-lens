"""LLM 客户端：用 OpenAI 兼容协议，同时支持通义千问 Qwen 与 DeepSeek。
切换模型只需改 .env，不改代码。

附带「调用埋点」（成本/延迟可观测）：每次 chat() 记录耗时与 token 用量，
get_metrics() 给出 P50/P95/P99 延迟、平均 token、估算成本——面试被问「一次查询多少钱/多慢」
能直接甩数字，也是上线降本的依据（配合语义缓存）。线程安全：图在工作线程里跑，故加锁。"""
import os
import time
import threading
from collections import deque

import httpx
from openai import OpenAI
from .config import LLM_BASE_URL, LLM_MODEL, LLM_API_KEY

# 企业代理 / 自签名证书场景：设 LLM_VERIFY_SSL=false 跳过 TLS 校验（仅开发环境用）
_VERIFY_SSL = os.getenv("LLM_VERIFY_SSL", "true").lower() not in ("false", "0", "no")

# ============================================================ 调用埋点（成本/延迟可观测）
_METRICS_LOCK = threading.Lock()
_LAT_MS: deque = deque(maxlen=1000)   # 最近 1000 次调用延迟(ms)，用于算分位数
_AGG = {"calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
# 单价（元/百万 token），按实际模型在 .env 配；缺省 0 = 不估算成本，只看 token/延迟
_PRICE_IN = float(os.getenv("LLM_PRICE_IN_PER_MTOK", "0"))
_PRICE_OUT = float(os.getenv("LLM_PRICE_OUT_PER_MTOK", "0"))


def _record(latency_ms: float, usage, error: bool = False):
    """累计一次调用的延迟与 token（fail-open：usage 缺失就只记延迟）。"""
    with _METRICS_LOCK:
        _AGG["calls"] += 1
        if error:
            _AGG["errors"] += 1
        _LAT_MS.append(latency_ms)
        if usage is not None:
            _AGG["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            _AGG["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
            _AGG["total_tokens"] += getattr(usage, "total_tokens", 0) or 0


def _pct(sorted_lat, p: float) -> float:
    """线性插值分位数。sorted_lat 已升序。"""
    if not sorted_lat:
        return 0.0
    k = (len(sorted_lat) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_lat) - 1)
    return sorted_lat[f] + (sorted_lat[c] - sorted_lat[f]) * (k - f)


def get_metrics() -> dict:
    """返回累计指标快照：调用次数/错误/token/分位延迟/估算成本。可挂到 /api/metrics 或评测脚本里。"""
    with _METRICS_LOCK:
        lat = sorted(_LAT_MS)
        agg = dict(_AGG)
    calls = agg["calls"] or 1
    return {
        **agg,
        "avg_total_tokens": round(agg["total_tokens"] / calls, 1),
        "p50_ms": round(_pct(lat, 0.50), 1),
        "p95_ms": round(_pct(lat, 0.95), 1),
        "p99_ms": round(_pct(lat, 0.99), 1),
        "est_cost_yuan": round(agg["prompt_tokens"] / 1e6 * _PRICE_IN
                               + agg["completion_tokens"] / 1e6 * _PRICE_OUT, 4),
    }


def reset_metrics():
    """清零（评测前调用，统计单批问题的成本/延迟）。"""
    with _METRICS_LOCK:
        _LAT_MS.clear()
        for k in _AGG:
            _AGG[k] = 0

# 稳定性关键：上游 LLM 偶发挂起时，无超时 = 整个 /api/ask 永久转圈、连接被一直占着。
# timeout 让请求最多等 LLM_TIMEOUT 秒；max_retries 处理偶发网络抖动（指数退避）。
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

# 惰性构造：OpenAI() 在 key 为空时构造即抛异常 → 原来没配 .env 连 import 都崩、/health 都起不来。
# 改为首次调用时才建客户端：服务能正常启动，只有真正用到 LLM 时才报清晰错误。
_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not LLM_API_KEY:
            raise RuntimeError("LLM_API_KEY 未配置：请在 .env 中设置（参考 README 环境变量一节）")
        _client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
                         timeout=LLM_TIMEOUT, max_retries=LLM_MAX_RETRIES,
                         http_client=httpx.Client(verify=_VERIFY_SSL))
    return _client


def chat(messages, temperature: float = 0.0, **kw) -> str:
    """同步对话，返回文本。Text2SQL 等确定性任务用 temperature=0。

    埋点：记录本次调用延迟与 token 用量（成功/失败都记一次，不重复计）。"""
    t0 = time.perf_counter()
    model = kw.pop("model", None) or LLM_MODEL
    try:
        resp = _get_client().chat.completions.create(
            model=model, messages=messages, temperature=temperature, **kw
        )
    except Exception:
        _record((time.perf_counter() - t0) * 1000, None, error=True)
        raise
    _record((time.perf_counter() - t0) * 1000, getattr(resp, "usage", None))
    return resp.choices[0].message.content or ""


def chat_with_tools(messages, temperature=0.0, model=None, tools=None):
    """Like chat() but returns the full message object for tool_calls access.
    Returns a ChatCompletionMessage with .content (str|None) and .tool_calls (list|None).
    """
    t0 = time.perf_counter()
    m = model or LLM_MODEL
    try:
        resp = _get_client().chat.completions.create(
            model=m, messages=messages, temperature=temperature, tools=tools
        )
    except Exception:
        _record((time.perf_counter() - t0) * 1000, None, error=True)
        raise
    _record((time.perf_counter() - t0) * 1000, getattr(resp, "usage", None))
    return resp.choices[0].message


def chat_stream(messages, temperature: float = 0.3, **kw):
    """流式对话，逐 token 产出（供洞察生成的 SSE 输出）。"""
    stream = _get_client().chat.completions.create(
        model=LLM_MODEL, messages=messages, temperature=temperature, stream=True, **kw
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
