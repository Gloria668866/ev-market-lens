"""RAG 离线入库管线（PRD-2 §5）：文档 → MinIO → 解析 → 父子分块 → BGE 向量化 → pgvector。

模块划分：
  store.py   对象存储（MinIO）：原始文件 put/get
  parse.py   可插拔解析器：PDF(PyMuPDF/pdfplumber)/HTML/纯文本 → 结构化块（标题层级/表格/页码）；MinerU 留接口
  chunk.py   结构感知 + 父子分块（overlap + 表格整体 + 标题增强 + token 控制）
  embed.py   BGE-large-zh 向量化（passage 不加前缀 + 归一化）+ token 计数
  pg.py      kb_document/kb_chunk 的 PostgreSQL(pgvector) 持久层（原生 psycopg）
  ingest.py  编排：存→解析→分块→embed→写库→置状态；重传软删
  tasks.py   Celery 异步任务（解析/切块/向量化耗时放后台）
"""
