"""Celery 异步任务：把已建档(parsing)的文档异步解析入库。

为什么异步（PRD-2 §19.4）：解析(MinerU/PDF)、切块、BGE 向量化都耗时（秒~分钟级），
不能阻塞上传请求。上传接口只「存 MinIO + 建 kb_document(parsing) + 投递任务」就立即返回 doc_id，
worker 后台跑 ingest，完成置 ready/失败置 failed，前端轮询状态。
"""
from app.celery_app import celery
from . import ingest


@celery.task(name="rag.ingest_document", bind=True, max_retries=1)
def ingest_document_task(self, doc_id: int):
    """异步执行 ingest.ingest_document；失败已在 ingest 内置 status=failed。"""
    return ingest.ingest_document(doc_id)
