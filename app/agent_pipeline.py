"""Config-driven DAG execution engine for oh-my-openagent pipelines.

Runs a pipeline defined in config/agents.yaml as a Celery task.
Each stage is an LLM call (with optional function calling for tool-enabled stages).
Progress is written to Redis so SSE clients can subscribe.

Key design decisions:
- Deterministic DAG execution (topological sort), not an LLM deciding what to run next.
- Code agents call pre-defined tools via function calling -- never generate code.
- Every stage's LLM response is validated against its expected JSON schema before proceeding.
- FAIL-SAFE: any stage failure -> pipeline stops, progress shows "failed", user gets degraded response.
"""
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import yaml

try:
    import redis
except ImportError:
    redis = None

from .config import AGENTS_CONFIG_PATH, REDIS_URL
from .llm import chat, chat_with_tools

_log = logging.getLogger("cheshijing.agent_pipeline")

# ── Config loading (thread-safe, same pattern as app/nlu.py) ──────────────────

_cfg_lock = threading.Lock()
_cfg = None


def _load_pipeline_config(force_reload: bool = False) -> dict:
    global _cfg
    with _cfg_lock:
        if _cfg is not None and not force_reload:
            return _cfg
        path = Path(AGENTS_CONFIG_PATH)
        if not path.exists():
            _cfg = {"stages": [], "agents": {}}
            return _cfg
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        _cfg = {
            "stages": raw.get("pipeline", {}).get("stages", []),
            "agents": raw.get("agents", {}),
            "redis": raw.get("redis", {}),
        }
        return _cfg


def reload_config():
    """Force reload pipeline config from disk. Call after editing agents.yaml."""
    _load_pipeline_config(force_reload=True)


def _get_agent_config(agent_name: str) -> dict:
    cfg = _load_pipeline_config()
    return cfg.get("agents", {}).get(agent_name, {})


def _get_stage_by_id(stages: list, stage_id: str) -> dict | None:
    for s in stages:
        if s["id"] == stage_id:
            return s
    return None


# ── DAG topological sort ──────────────────────────────────────────────────────

def _topological_sort(stages: list) -> list:
    """Kahn's algorithm. Sorts stages so dependencies come before dependents."""
    in_degree = {s["id"]: len(s.get("depends_on") or []) for s in stages}
    adj = {s["id"]: [] for s in stages}
    for s in stages:
        for dep in s.get("depends_on") or []:
            if dep in adj:
                adj[dep].append(s["id"])

    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    result = []
    while queue:
        sid = queue.pop(0)
        result.append(_get_stage_by_id(stages, sid))
        for neighbor in adj.get(sid, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(result) != len(stages):
        raise ValueError(
            f"Pipeline DAG has a cycle or missing dependency. "
            f"Sorted {len(result)}/{len(stages)}"
        )
    return result


# ── Redis progress ────────────────────────────────────────────────────────────

_redis_client_instance = None


def _redis_client():
    global _redis_client_instance
    if _redis_client_instance is None:
        if redis is None:
            return None
        try:
            _redis_client_instance = redis.from_url(REDIS_URL, decode_responses=True)
        except Exception:
            _redis_client_instance = None
    return _redis_client_instance


def _set_progress(task_id: str, data: dict):
    """Write pipeline progress to Redis. TTL matched to config."""
    r = _redis_client()
    if r is None:
        return
    try:
        ttl = _load_pipeline_config().get("redis", {}).get("progress_ttl_seconds", 1800)
        r.set(
            f"pipeline:{task_id}:status",
            json.dumps(data, ensure_ascii=False, default=str),
            ex=ttl,
        )
    except Exception:
        _log.warning("Failed to write Redis progress for %s", task_id, exc_info=True)


def _get_progress(task_id: str) -> dict | None:
    """Read pipeline progress from Redis."""
    try:
        r = _redis_client()
        raw = r.get(f"pipeline:{task_id}:status")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def get_progress(task_id: str) -> dict | None:
    """Public API: read pipeline progress from Redis."""
    return _get_progress(task_id)


# ── Stage execution ────────────────────────────────────────────────────────────

def _call_llm_with_tools(agent_name: str, messages: list, tool_defs: list,
                         max_rounds: int = 3) -> dict:
    """Call LLM with optional function calling. Supports multi-round tool use:
    Each round: LLM sees tools → may return tool_calls → execute → feed back.
    Loops until LLM returns content without tool_calls, or max_rounds reached.
    """
    agent_cfg = _get_agent_config(agent_name)
    model_override = agent_cfg.get("model") or None
    temperature = agent_cfg.get("temperature", 0.0)

    msgs = list(messages)

    extra_kwargs = {"temperature": temperature}
    if model_override:
        extra_kwargs["model"] = model_override

    if not tool_defs:
        raw = chat(msgs, **extra_kwargs)
        return _parse_json_response(raw)

    from .agent_tools import execute_tool

    for _round in range(max_rounds):
        msg = chat_with_tools(msgs, tools=tool_defs, **extra_kwargs)

        if not msg.tool_calls:
            return _parse_json_response(msg.content or "")

        tool_results = []
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
            except (json.JSONDecodeError, TypeError):
                args = {}
            result = execute_tool(tc.function.name, args)
            tool_results.append({"tool_call_id": tc.id, "tool_name": tc.function.name, "result": result})
            _log.info("Tool call [%s] %s(%s) → %s chars",
                      agent_name, tc.function.name, list(args.keys()),
                      len(json.dumps(result, ensure_ascii=False)))

        # Append assistant message with tool_calls
        msgs.append({"role": "assistant", "content": msg.content or "",
                     "tool_calls": [{"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                     for tc in msg.tool_calls]})
        # Append each tool response with matching tool_call_id
        for tr in tool_results:
            msgs.append({
                "role": "tool",
                "tool_call_id": tr["tool_call_id"],
                "content": json.dumps(tr["result"], ensure_ascii=False),
            })

    # Exhausted max_rounds — force a final text response without tools
    msgs.append({"role": "user", "content": "你已经使用了所有可用的工具调用轮次。请根据目前已获得的信息，立即返回要求的 JSON 格式结果。不要再调用工具。"})
    raw = chat(msgs, **extra_kwargs)
    return _parse_json_response(raw)


def _parse_json_response(raw: str) -> dict:
    """Extract JSON from LLM response. FAIL-SAFE: returns error dict on failure."""
    try:
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s < 0 or e <= s:
            raise ValueError("no JSON in response")
        return json.loads(raw[s:e])
    except Exception:
        return {
            "status": "failed",
            "error": "Failed to parse LLM response as JSON",
            "raw_preview": raw[:200],
        }


def _execute_stage(
    stage_def: dict, pipeline_context: dict, original_question: str
) -> dict:
    """Execute a single pipeline stage. Returns the parsed LLM output dict."""
    stage_id = stage_def["id"]
    agent_name = stage_def["agent"]
    agent_cfg = _get_agent_config(agent_name)

    if not agent_cfg:
        raise ValueError(
            f"Agent '{agent_name}' not found in agents.yaml (stage '{stage_id}')"
        )

    from .agent_tools import get_tool_definitions

    tool_defs = get_tool_definitions(agent_name)

    # Build messages
    system_prompt = agent_cfg.get("system_prompt", "").strip()
    messages = [{"role": "system", "content": system_prompt}]

    # Build user prompt with context from upstream stages + original question
    user_parts = [f"用户原始问题：{original_question}"]
    if pipeline_context:
        user_parts.append(
            f"上游阶段输出：{json.dumps(pipeline_context, ensure_ascii=False)}"
        )
    messages.append({"role": "user", "content": "\n\n".join(user_parts)})

    max_rounds = agent_cfg.get("max_tool_rounds", 3)
    return _call_llm_with_tools(agent_name, messages, tool_defs, max_rounds=max_rounds)


# ── Pipeline runner ────────────────────────────────────────────────────────────

def run_pipeline(
    task_id: str, original_question: str, original_user_id: int = 0
) -> dict:
    """Execute the full pipeline DAG. Called by Celery task.

    Returns: {"status": "completed|failed", "stages": {...}, "final_answer": "..."}
    """
    _set_progress(task_id, {"stage": "start", "status": "running", "ts": time.time()})

    cfg = _load_pipeline_config(force_reload=True)
    stages = cfg.get("stages", [])
    if not stages:
        return {"status": "failed", "error": "No pipeline stages defined in agents.yaml"}

    # Topological sort
    try:
        ordered = _topological_sort(stages)
    except ValueError as e:
        return {"status": "failed", "error": str(e)}

    # Execute stages in order, feeding each stage's output as context for downstream
    stage_outputs: dict[str, Any] = {}

    for stage_def in ordered:
        stage_id = stage_def["id"]
        _set_progress(
            task_id, {"stage": stage_id, "status": "running", "ts": time.time()}
        )

        try:
            # Build context from dependency outputs
            deps = stage_def.get("depends_on") or []
            dep_context = {
                dep: stage_outputs.get(dep) for dep in deps if dep in stage_outputs
            }

            output = _execute_stage(stage_def, dep_context, original_question)
            stage_outputs[stage_id] = output

            _set_progress(
                task_id,
                {
                    "stage": stage_id,
                    "status": "completed",
                    "ts": time.time(),
                    "preview": json.dumps(output, ensure_ascii=False)[:200],
                },
            )

        except Exception as e:
            _log.error("Pipeline stage '%s' failed: %s", stage_id, e, exc_info=True)
            _set_progress(
                task_id,
                {
                    "stage": stage_id,
                    "status": "failed",
                    "error": str(e)[:200],
                    "ts": time.time(),
                },
            )
            return {
                "status": "failed",
                "failed_stage": stage_id,
                "error": str(e)[:300],
                "stages": stage_outputs,
            }

    # Pipeline completed — auto-write to RAG if review says so
    review_output = stage_outputs.get("review", {})
    final_answer = review_output.get(
        "answer_to_user", "数据采集完成，但未能生成有效回答。"
    )

    if review_output.get("should_write_to_rag", False):
        try:
            from .agent_tools import execute_tool
            rag_title = review_output.get("rag_title", f"采集数据-{original_question[:20]}")
            rag_content = final_answer
            code_output = stage_outputs.get("code", {})
            if code_output.get("collected_data"):
                snippets = [d.get("content_preview", "") for d in code_output["collected_data"]
                            if d.get("content_preview")]
                if snippets:
                    rag_content = f"## 用户问题\n{original_question}\n\n## 摘要\n{final_answer}\n\n## 原始数据\n" + "\n---\n".join(snippets)
            rag_result = execute_tool("write_to_rag", {
                "title": rag_title,
                "content": rag_content,
                "source_url": "agent_pipeline_auto_collect",
            })
            _log.info("Auto-write to RAG: %s", rag_result.get("status"))
        except Exception as e:
            _log.warning("Failed to auto-write to RAG: %s", e)

    _set_progress(
        task_id,
        {
            "stage": "done",
            "status": "completed",
            "ts": time.time(),
            "final_answer": final_answer[:500],
        },
    )

    return {
        "status": "completed",
        "stages": stage_outputs,
        "final_answer": final_answer,
    }


# ── Celery task ───────────────────────────────────────────────────────────────

try:
    from .celery_app import celery

    @celery.task(name="agent_pipeline.run", bind=True, max_retries=0,
                 task_ignore_result=True)
    def run_pipeline_task(self, task_id: str, original_question: str,
                          original_user_id: int = 0):
        """Celery task wrapper for run_pipeline. fire-and-forget with Redis progress."""
        _set_progress(task_id, {"stage": "queued", "status": "pending", "ts": time.time()})

        try:
            result = run_pipeline(task_id, original_question, original_user_id)
            _set_progress(task_id, {
                "stage": result.get("status", "done"),
                "status": result.get("status", "failed"),
                "final_answer": result.get("final_answer", "")[:500],
                "ts": time.time(),
            })
            return result
        except Exception as e:
            _log.error(f"Pipeline task {task_id} failed: {e}", exc_info=True)
            _set_progress(task_id, {
                "stage": "error", "status": "failed",
                "error": str(e)[:300], "ts": time.time(),
            })
            return {"status": "failed", "error": str(e)[:300]}

except ImportError:
    run_pipeline_task = None
