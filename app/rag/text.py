"""中文分词（jieba）——给全文检索通道用。

为什么需要：PG `to_tsvector('simple')` 不切中文（整句当一个 token）→ 中文 query 召回 0，
混合召回退化成纯向量，政策/数字/专名类（向量弱项）召回垮（评测实测 recall 乘联会 0.28）。
修法（纯应用层，不依赖 pg_jieba 扩展）：入库把 content 用 jieba 切成空格分隔词存进 content_tokens，
PG simple 对空格分词即生效；查询同样 jieba 切词、用 OR 组 tsquery 提召回。
"""
import re

import jieba

# 只保留中英数 token（去标点/空白），避免污染 tsquery
_VALID = re.compile(r"[一-鿿A-Za-z0-9]+")


def tokens_for_index(text: str) -> str:
    """入库：搜索引擎模式细粒度切词 → 空格分隔串，存 content_tokens。"""
    if not text:
        return ""
    return " ".join(t for t in jieba.cut_for_search(text) if t.strip())


def query_terms(query: str):
    """查询：切词 → 干净 term 列表（去标点/停用空白）。"""
    if not query:
        return []
    out, seen = [], set()
    for t in jieba.cut(query):
        t = t.strip()
        if t and _VALID.fullmatch(t) and t not in seen:
            seen.add(t)
            out.append(t)
    return out
