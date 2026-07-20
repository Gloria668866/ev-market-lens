-- ============================================================
-- 车市镜 · 应用层表（登录 / 会话历史 / 知识库）
-- 方言：PostgreSQL（向量列需 pgvector 扩展）；括号注 SQLite 差异
-- 设计依据：PRD-2 §6（存储）+ §17（登录模块）
-- 分析库表（dim_*/fact_*）见 sql/schema.sql
-- 说明：知识库向量建议直接用 PostgreSQL+pgvector；本地 demo 若用 SQLite，
--       向量改用 Chroma 存（SQLite 不适合存向量）。
-- ============================================================

-- 需要向量功能时先开启扩展（PostgreSQL）：
-- CREATE EXTENSION IF NOT EXISTS vector;

-- ---------- 用户（登录模块）----------
CREATE TABLE users (
    user_id       BIGSERIAL PRIMARY KEY,         -- SQLite: INTEGER PRIMARY KEY AUTOINCREMENT
    username      VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,          -- bcrypt 哈希，绝不存明文
    nickname      VARCHAR(64),
    status        VARCHAR(16) DEFAULT 'active',    -- active/disabled
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP
);

-- ---------- 会话 ----------
CREATE TABLE conversation (
    conv_id    BIGSERIAL PRIMARY KEY,
    user_id    BIGINT REFERENCES users(user_id),  -- 归属用户（多租户隔离）
    title      VARCHAR(128),                       -- 取首个问题摘要
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP                            -- 软删除
);

-- ---------- 消息 ----------
CREATE TABLE message (
    msg_id      BIGSERIAL PRIMARY KEY,
    conv_id     BIGINT REFERENCES conversation(conv_id),
    role        VARCHAR(16) NOT NULL,               -- user / assistant
    content     TEXT,                               -- 用户问题 或 助手最终回答
    intent      VARCHAR(16),                        -- 助手轮：sql/rag/hybrid/clarify
    sql_text    TEXT,                               -- 走 Text2SQL 时记录最终 SQL（可回溯/调试）
    chart_spec  JSONB,                              -- ECharts 规格（SQLite: TEXT 存 JSON）
    citations   JSONB,                              -- RAG 引用 [{doc_id,page_no,chunk_id}]
    result_meta JSONB,                              -- 行数/耗时/重试次数/置信度
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_message_conv ON message(conv_id);
CREATE INDEX idx_conversation_user ON conversation(user_id);

-- ---------- 知识库文档 ----------
CREATE TABLE kb_document (
    doc_id      BIGSERIAL PRIMARY KEY,
    user_id     BIGINT REFERENCES users(user_id),   -- 归属用户（检索时按此过滤，防串数据）
    filename    VARCHAR(256),
    file_type   VARCHAR(16),                         -- pdf/docx/html
    source_uri  VARCHAR(512),                        -- MinIO 对象路径
    title       VARCHAR(256),
    status      VARCHAR(16) DEFAULT 'parsing',       -- parsing/ready/failed
    chunk_count INTEGER DEFAULT 0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at  TIMESTAMP                             -- 软删除
);

-- ---------- 文档切片（父子分块 + 向量）----------
-- 设计依据：PRD-2 §5.3.2（父子分块）/ §5.4.1（父块归并）/ §5.6（字段推导）
-- 父、子同表，用 level 区分；子行 parent_chunk_id 指向父行；仅子块参与向量检索。
CREATE TABLE kb_chunk (
    chunk_id        BIGSERIAL PRIMARY KEY,
    doc_id          BIGINT REFERENCES kb_document(doc_id),
    user_id         BIGINT,                          -- 冗余：检索热路径 WHERE user_id 直接过滤，免 join（多租户隔离）
    chunk_index     INTEGER,                         -- 文档内顺序号（相邻父块合并依据）
    level           VARCHAR(8),                      -- 'child' / 'parent'（父子分块角色）
    parent_chunk_id BIGINT,                          -- child→所属 parent；parent 行为 NULL
    is_retrievable  BOOLEAN DEFAULT TRUE,            -- true=子块进向量检索；false=父块仅作上下文回填
    chunk_type      VARCHAR(16) DEFAULT 'text',      -- text / table / title
    heading_path    TEXT,                            -- 章节标题路径（标题增强 + 溯源展示）
    content         TEXT,                            -- 展示给用户的原文（引用卡显示）
    content_embed   TEXT,                            -- 实际送 BGE 的文本（原文+标题前缀）；NULL=同 content
    embedding       vector(1024),                    -- BGE-large-zh；仅子块有；需 pgvector
    page_no         INTEGER,                         -- 引用溯源
    token_count     INTEGER,                         -- 校验 <=512 / 组装上下文控预算
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_kbchunk_doc    ON kb_chunk(doc_id);
CREATE INDEX idx_kbchunk_parent ON kb_chunk(parent_chunk_id);
CREATE INDEX idx_kbchunk_user   ON kb_chunk(user_id);
-- 向量检索索引（pgvector）：只对可检索的子块建（partial index，省空间提速）：
-- CREATE INDEX idx_kbchunk_vec ON kb_chunk USING hnsw (embedding vector_cosine_ops) WHERE is_retrievable;
-- 备选：CREATE INDEX idx_kbchunk_vec ON kb_chunk USING ivfflat (embedding vector_cosine_ops) WHERE is_retrievable;
-- 混合召回的全文检索（中文需配分词，如 zhparser/pg_jieba）：
-- CREATE INDEX idx_kbchunk_fts ON kb_chunk USING gin (to_tsvector('simple', content));
