"""Shared capacity guard for every cost-bearing interactive question."""
import threading

from fastapi import HTTPException

from .config import ASK_MAX_CONCURRENCY


ASK_SLOTS = threading.BoundedSemaphore(ASK_MAX_CONCURRENCY)


def acquire_ask_slot(slots=ASK_SLOTS) -> None:
    """Fail fast before quota reservation when all model slots are occupied."""
    if not slots.acquire(blocking=False):
        raise HTTPException(
            503,
            f"当前分析任务已满（最多 {ASK_MAX_CONCURRENCY} 个并发），请稍后重试",
        )


def release_ask_slot(slots=ASK_SLOTS) -> None:
    slots.release()
