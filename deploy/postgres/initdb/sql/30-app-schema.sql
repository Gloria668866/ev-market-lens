-- ============================================================
-- 车市镜 · 应用库（app）建表脚本  —— 由 docker-compose 初始化时载入
-- 方言：PostgreSQL（kb_chunk.embedding 需 pgvector，载入前已 CREATE EXTENSION vector）
--
-- 重要设计决策（2026-05-25，运维 T14 拉基础设施时定）：
--   users/conversation/message/kb_document 的列名**对齐当前后端 app/models.py**
--   （主键 id、外键 conversation_id 等），而**不是** sql/schema_app.sql 里的
--   user_id/conv_id/msg_id/doc_id 命名 —— 否则后端 ORM 查询会全部报错（查 users.id
--   但表里只有 user_id）。kb_chunk（父子分块 + 向量）则取自 schema_app.sql，给 RAG 用。
--   kb_document 在 models.py 必需列之外，额外补了 schema_app.sql 的若干 RAG 列
--   （file_type/source_uri/title/chunk_count/deleted_at，均 nullable）——
--   后端 ORM 只读写核心列，多出来的列留给后续 RAG/MinerU 入库用，互不影响。
-- ============================================================

-- ---------- 用户（登录模块，对齐 app/models.py: User）----------
CREATE TABLE users (
    id             BIGSERIAL PRIMARY KEY,
    username       VARCHAR(64) UNIQUE NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,           -- bcrypt 哈希，绝不存明文
    nickname       VARCHAR(64),
    role           VARCHAR(16) DEFAULT 'user',       -- 'user' / 'admin'
    disabled       BOOLEAN DEFAULT FALSE,            -- 禁用后不能登录
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at  TIMESTAMP
);

-- ---------- 会话（对齐 app/models.py: Conversation）----------
CREATE TABLE conversation (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),    -- 归属用户（多租户隔离）
    title       VARCHAR(255),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------- 消息（对齐 app/models.py: Message）----------
CREATE TABLE message (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  BIGINT NOT NULL REFERENCES conversation(id),
    user_id          BIGINT NOT NULL REFERENCES users(id),   -- 冗余便于按用户过滤
    role             VARCHAR(16) NOT NULL,                   -- 'user' / 'assistant'
    content          TEXT,
    intent           VARCHAR(16),                            -- sql / doc / chat
    sql_text         TEXT,                                   -- 助手消息生成的 SQL（可溯源）
    result_meta      TEXT,                                   -- JSON：图表描述符/列+行/引用/trace（历史会话还原）
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------- 知识库文档（对齐 app/models.py: KbDocument，并补 RAG 用列）----------
CREATE TABLE kb_document (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),    -- 归属用户（检索按此过滤，防串数据）
    filename    VARCHAR(255) NOT NULL,
    status      VARCHAR(16) DEFAULT 'ready',             -- parsing / ready / failed
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- 以下为 RAG/MinerU 入库用的扩展列（后端 ORM 暂不读写，先留位）：
    file_type   VARCHAR(16),                             -- pdf/docx/html
    source_uri  VARCHAR(512),                            -- MinIO 对象路径
    title       VARCHAR(256),
    chunk_count INTEGER DEFAULT 0,
    deleted_at  TIMESTAMP                                 -- 软删除
);

-- ---------- 收藏看板（对齐 app/models.py: SavedInsight）----------
CREATE TABLE saved_insight (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),    -- 归属用户（隔离）
    title       VARCHAR(255),
    question    TEXT,
    intent      VARCHAR(16),                             -- sql / rag / hybrid
    payload     TEXT,                                    -- JSON 快照：columns/rows/chart/insight/citations/sql
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------- 一键分享（对齐 app/models.py: SharedInsight）----------
CREATE TABLE shared_insight (
    id          BIGSERIAL PRIMARY KEY,
    token       VARCHAR(32) UNIQUE NOT NULL,             -- 公开只读访问 token（/s/{token}）
    user_id     BIGINT REFERENCES users(id),            -- 创建者（可空）
    title       VARCHAR(255),
    question    TEXT,
    intent      VARCHAR(16),
    payload     TEXT,                                    -- JSON 快照（同上）
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_conversation_user ON conversation(user_id);
CREATE INDEX idx_message_user      ON message(user_id);
CREATE INDEX idx_message_conv      ON message(conversation_id);
CREATE INDEX idx_kb_document_user  ON kb_document(user_id);
CREATE INDEX idx_saved_insight_user ON saved_insight(user_id);
CREATE INDEX idx_shared_insight_token ON shared_insight(token);

-- ---------- 文档切片（父子分块 + 向量；取自 sql/schema_app.sql）----------
-- 设计依据：PRD-2 §5.3.2（父子分块）/ §5.4.1（父块归并）/ §5.6（字段推导）
-- 父、子同表用 level 区分；子行 parent_chunk_id 指父行；仅子块（is_retrievable）参与向量检索。
-- 注意：doc_id 外键指向 kb_document(id)（对齐上面的 id 主键，非 schema_app.sql 的 doc_id）。
CREATE TABLE kb_chunk (
    chunk_id        BIGSERIAL PRIMARY KEY,
    doc_id          BIGINT REFERENCES kb_document(id),
    user_id         BIGINT,                          -- 冗余：检索热路径 WHERE user_id 直接过滤，免 join（多租户隔离）
    chunk_index     INTEGER,                         -- 文档内顺序号（相邻父块合并依据）
    level           VARCHAR(8),                      -- 'child' / 'parent'（父子分块角色）
    parent_chunk_id BIGINT,                          -- child→所属 parent；parent 行为 NULL
    is_retrievable  BOOLEAN DEFAULT TRUE,            -- true=子块进向量检索；false=父块仅作上下文回填
    chunk_type      VARCHAR(16) DEFAULT 'text',      -- text / table / title
    heading_path    TEXT,                            -- 章节标题路径（标题增强 + 溯源展示）
    content         TEXT,                            -- 展示给用户的原文（引用卡显示）
    content_embed   TEXT,                            -- 实际送 BGE 的文本（原文+标题前缀）；NULL=同 content
    content_tokens  TEXT,                            -- jieba 分词后的 content（空格分隔），供中文全文检索
    embedding       vector(1024),                    -- BGE-large-zh；仅子块有；需 pgvector
    page_no         INTEGER,                         -- 引用溯源
    token_count     INTEGER,                         -- 校验 <=512 / 组装上下文控预算
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_kbchunk_doc    ON kb_chunk(doc_id);
CREATE INDEX idx_kbchunk_parent ON kb_chunk(parent_chunk_id);
CREATE INDEX idx_kbchunk_user   ON kb_chunk(user_id);
-- 向量检索索引（pgvector HNSW）：只对可检索的子块建（partial index，省空间提速）
CREATE INDEX idx_kbchunk_vec ON kb_chunk USING hnsw (embedding vector_cosine_ops) WHERE is_retrievable;
-- 中文全文检索：建在 jieba 分词后的 content_tokens 上（PG simple 不切中文，必须先应用层分词）。
-- 入库由 app/rag 写 content_tokens；检索 app/rag/pg.py 用 jieba 切 query 组 OR tsquery。
CREATE INDEX idx_kbchunk_fts ON kb_chunk USING gin (to_tsvector('simple', content_tokens));
