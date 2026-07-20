"""BGE-large-zh 向量化（本地，1024 维）。

要点（PRD-2 §5.3/§5.4/§5.8）：
- query/passage **非对称**：检索侧 query 要加指令前缀，入库的 passage **不加前缀**；加错召回明显掉。
- **归一化**（normalize）后用余弦相似度（pgvector vector_cosine_ops / HNSW 同款）。
- **512 token 硬上限**：超了被截断丢语义；token 用模型自带 tokenizer 精确数（中文按 token 不按字符）。
- **版本一致性**：入库与检索必须同一模型同一版本同样归一化，否则向量空间不一致、召回全乱（§5.8）。
  模型名/版本在 config（EMBED_MODEL_NAME/VERSION）；换模型必须全量重算、重建 HNSW。
"""
import os
import re
import threading

from ..config import EMBED_MODEL_NAME, EMBED_MAX_TOKENS, RERANK_MODEL_NAME

import logging; _log = logging.getLogger("cheshijing.embed")

# bge-*-zh-v1.5 检索 query 的指令前缀（passage 不加）
_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

_model = "unloaded"        # "unloaded" / None(不可用→词法降级) / SentenceTransformer 实例
_reranker = "unloaded"     # "unloaded" / None(不可用) / CrossEncoder 实例
_model_lock = threading.Lock()    # P2 FIX: 并发加载时多个线程同时进入会重复加载 1GB+ 模型
_reranker_lock = threading.Lock()


def get_model():
    """懒加载单例（双重检查锁定）。模型缺失/损坏/无法下载 → 返回 None（全链路降级为词法检索，绝不让服务崩）。"""
    global _model
    if _model == "unloaded":
        with _model_lock:
            if _model == "unloaded":
                try:
                    from sentence_transformers import SentenceTransformer
                    m = SentenceTransformer(EMBED_MODEL_NAME)
                    m.max_seq_length = EMBED_MAX_TOKENS
                    _model = m
                except Exception as e:
                    _log.warning(f"向量模型不可用，RAG 降级为词法检索（jieba 全文 + RRF）：{e}")
                    _model = None
    return _model


def vectors_available() -> bool:
    return get_model() is not None


def _heuristic_tokens(t: str) -> int:
    """无 tokenizer 时的兜底（中文≈1token/字，英文≈/4字符）。"""
    cjk = len(re.findall(r"[一-鿿]", t or ""))
    return max(1, cjk + (len(t or "") - cjk) // 4)


def count_tokens(text: str) -> int:
    """优先用模型 tokenizer 精确数；模型不可用则启发式估算（切块仍能进行）。"""
    m = get_model()
    if m is None:
        return _heuristic_tokens(text)
    return len(m.tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"])


def embed_passages(texts):
    """入库侧：passage 不加前缀、归一化。模型不可用 → 返回 []（调用方走词法检索）。"""
    if not texts or get_model() is None:
        return []
    vecs = get_model().encode(texts, normalize_embeddings=True,
                              batch_size=32, show_progress_bar=False)
    return [v.tolist() for v in vecs]


def embed_query(text: str):
    """检索侧：query 加指令前缀、归一化。模型不可用 → 返回 None（调用方跳过向量召回）。"""
    if get_model() is None:
        return None
    vec = get_model().encode([_QUERY_INSTRUCTION + text], normalize_embeddings=True)[0]
    return vec.tolist()


def _get_reranker():
    """懒加载 bge-reranker（CrossEncoder）；模型不可用返回 None（调用方降级用 RRF 分）。"""
    global _reranker
    if _reranker == "unloaded":
        try:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder(RERANK_MODEL_NAME, max_length=512)
        except Exception as e:               # 模型没下到/加载失败 → 降级
            _log.warning(f"bge-reranker 不可用，降级为 RRF 排序：{e}")
            _reranker = None
    return _reranker


def rerank_scores(query: str, passages):
    """对 (query, passage) 精排，返回 [0,1] 相关分。reranker 不可用 → None。
    （sentence-transformers 的 CrossEncoder 对单标签模型默认已套 sigmoid，输出即 0~1，不再二次 sigmoid。）"""
    rr = _get_reranker()
    if rr is None or not passages:
        return None
    scores = rr.predict([(query, p) for p in passages])
    return [float(s) for s in scores]
