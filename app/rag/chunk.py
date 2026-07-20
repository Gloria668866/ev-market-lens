"""结构感知 + 父子分块（PRD-2 §5.3）。

为什么这么切（不是无脑定长）：
- **结构感知**：先按解析出的标题层级分「小节(section)」，在自然语义边界断；段落超长再按句子(。！？；)递归切，绝不切句子中间。
- **父子分块(small-to-big)**：
    子块(child, ~280 token)粒度小、语义聚焦 → 真正进向量检索(is_retrievable=true,有 embedding)；
    父块(parent, 完整小节 ~900 token)上下文全 → 不进检索(is_retrievable=false,无 embedding)，子块命中后回填给 LLM。
  父子同表用 level 区分，子块 parent_chunk_id 指父块。
- **overlap ~64 token**：相邻子块边界重叠，防答案落接缝被劈断。
- **表格整体保留**：一张表 = 一个 child（不按句子切碎），chunk_type=table。
- **标题增强**：子块送 embed 的文本(content_embed)前面拼章节路径(heading_path)，把被切走的上下文补回来；
  展示用的 content 不含前缀（展示≠送embed，分开防污染，§5.6）。
- **512 token 硬约束**：全部按 token 控（中文按 token 不按字符）。

产出：有序 chunk 列表（父子交错），child 的 parent_ref 指向其 parent 在列表中的下标；
入库时先写 parent 拿到真实 chunk_id，再回填 child.parent_chunk_id（见 pg.py / ingest.py）。
"""
import re

from ..config import CHUNK_CHILD_TOKENS, CHUNK_PARENT_TOKENS, CHUNK_OVERLAP_TOKENS

_SENT_SPLIT = re.compile(r"(?<=[。！？；!?;\n])")     # 句子边界（保留分隔符）


def _heuristic_tokens(t: str) -> int:
    """无 tokenizer 时的兜底估算（中文≈1token/字，英文≈/4字符）。"""
    cjk = len(re.findall(r"[一-鿿]", t))
    other = len(t) - cjk
    return max(1, cjk + other // 4)


def _sentences(text: str):
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def _window(sentences, count, child_tokens, overlap_tokens):
    """把句子贪心打包成 ~child_tokens 的窗口，相邻窗口 overlap ~overlap_tokens。"""
    windows, cur, cur_tok = [], [], 0
    for s in sentences:
        st = count(s)
        if cur and cur_tok + st > child_tokens:
            windows.append("".join(cur))
            # 回退尾部句子做 overlap
            back, btok = [], 0
            for prev in reversed(cur):
                pt = count(prev)
                if btok + pt > overlap_tokens:
                    break
                back.insert(0, prev); btok += pt
            cur, cur_tok = back[:], btok
        cur.append(s); cur_tok += st
    if cur:
        windows.append("".join(cur))
    return windows


def build_chunks(blocks, count_tokens=None):
    """blocks(解析产物) → 父子 chunk 列表。count_tokens 注入真实 tokenizer（缺省用兜底估算）。"""
    count = count_tokens or _heuristic_tokens
    chunks = []

    # —— 1) 按 heading_path 聚成小节 ——
    sections, cur_path, cur_blocks = [], None, []
    for b in blocks:
        if b["type"] == "heading":
            if cur_blocks:
                sections.append((cur_path, cur_blocks)); cur_blocks = []
            cur_path = b["heading_path"]
            continue
        path = b["heading_path"]
        if cur_path is None:
            cur_path = path
        if path != cur_path and cur_blocks:
            sections.append((cur_path, cur_blocks)); cur_blocks = []
            cur_path = path
        cur_blocks.append(b)
    if cur_blocks:
        sections.append((cur_path, cur_blocks))

    # —— 2) 每个小节 → 父块（超长则拆多个父块）→ 子块 ——
    for path, sec_blocks in sections:
        heading_path = " > ".join(path or [])
        # 把小节内容块按父块预算分组（表格不与文本合并计数过头，仍按 token 累加）
        groups, g, g_tok = [], [], 0
        for b in sec_blocks:
            bt = count(b["text"])
            if g and g_tok + bt > CHUNK_PARENT_TOKENS:
                groups.append(g); g, g_tok = [], 0
            g.append(b); g_tok += bt
        if g:
            groups.append(g)

        for group in groups:
            parent_text = "\n".join(b["text"] for b in group)
            parent_type = "table" if all(b["type"] == "table" for b in group) else "text"
            parent_idx = len(chunks)
            chunks.append({
                "level": "parent", "parent_ref": None, "is_retrievable": False,
                "chunk_type": parent_type, "heading_path": heading_path,
                "content": parent_text, "content_embed": None,
                "page_no": group[0]["page_no"], "token_count": count(parent_text),
            })
            # 子块：表格整体成块；文本按句子窗口切
            for b in group:
                if b["type"] == "table":
                    pieces = [(b["text"], "table")]
                else:
                    pieces = [(w, "text") for w in _window(
                        _sentences(b["text"]), count, CHUNK_CHILD_TOKENS, CHUNK_OVERLAP_TOKENS)]
                for content, ctype in pieces:
                    if not content.strip():
                        continue
                    embed_text = (heading_path + "\n" + content) if heading_path else content
                    chunks.append({
                        "level": "child", "parent_ref": parent_idx, "is_retrievable": True,
                        "chunk_type": ctype, "heading_path": heading_path,
                        "content": content, "content_embed": embed_text,
                        "page_no": b["page_no"], "token_count": count(content),
                    })

    # —— 3) 文档内顺序号 ——
    for i, c in enumerate(chunks):
        c["chunk_index"] = i
    return chunks
