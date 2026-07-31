-- ============================================================
-- 车市镜 · 应用库 PostgreSQL 参考 Schema
-- 权威实现：app/models.py（ORM）+ app/rag/pg.py（向量切片）。
-- 生产首启副本：deploy/postgres/initdb/sql/30-app-schema.sql。
-- 本地开发不执行本文件：ORM 创建 app.db，RAG local_store 使用独立 SQLite+numpy。
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
    id             BIGSERIAL PRIMARY KEY,
    username       VARCHAR(64) UNIQUE NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,
    nickname       VARCHAR(64),
    role           VARCHAR(16) DEFAULT 'user',
    disabled       BOOLEAN DEFAULT FALSE,
    token_version  INTEGER DEFAULT 0,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at  TIMESTAMP
);

CREATE TABLE conversation (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),
    title       VARCHAR(255),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE message (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  BIGINT NOT NULL REFERENCES conversation(id),
    user_id          BIGINT NOT NULL REFERENCES users(id),
    role             VARCHAR(16) NOT NULL,
    content          TEXT,
    intent           VARCHAR(16),
    sql_text         TEXT,
    result_meta      TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE kb_document (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT REFERENCES users(id),       -- NULL=系统公共知识
    filename    VARCHAR(255) NOT NULL,
    status      VARCHAR(16) DEFAULT 'ready',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    file_type   VARCHAR(16),
    source_uri  VARCHAR(512),
    title       VARCHAR(256),
    chunk_count INTEGER DEFAULT 0,
    deleted_at  TIMESTAMP
);

CREATE TABLE saved_insight (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),
    title       VARCHAR(255),
    question    TEXT,
    intent      VARCHAR(16),
    payload     TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE shared_insight (
    id          BIGSERIAL PRIMARY KEY,
    token       VARCHAR(32) UNIQUE NOT NULL,
    user_id     BIGINT REFERENCES users(id),
    title       VARCHAR(255),
    question    TEXT,
    intent      VARCHAR(16),
    payload     TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_profile (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    key             VARCHAR(64) NOT NULL,
    value           TEXT NOT NULL,
    confidence      DOUBLE PRECISION DEFAULT 1.0,
    evidence_count  INTEGER DEFAULT 1,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_profile_uid_key UNIQUE(user_id, key)
);

CREATE TABLE memory_episode (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT NOT NULL REFERENCES users(id),
    conversation_id  BIGINT NOT NULL REFERENCES conversation(id),
    summary          TEXT NOT NULL,
    entities_json    TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_episode_uid_conv UNIQUE(user_id, conversation_id)
);

CREATE TABLE kb_chunk (
    chunk_id        BIGSERIAL PRIMARY KEY,
    doc_id          BIGINT REFERENCES kb_document(id),
    user_id         BIGINT,                         -- NULL=公共；非NULL=用户私有
    chunk_index     INTEGER,
    level           VARCHAR(8),
    parent_chunk_id BIGINT,
    is_retrievable  BOOLEAN DEFAULT TRUE,
    chunk_type      VARCHAR(16) DEFAULT 'text',
    heading_path    TEXT,
    content         TEXT,
    content_embed   TEXT,
    content_tokens  TEXT,
    embedding       vector(1024),
    embedding_model_version VARCHAR(128),
    embedding_dim   INTEGER,
    page_no         INTEGER,
    token_count     INTEGER,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_conversation_user ON conversation(user_id);
CREATE INDEX idx_message_user ON message(user_id);
CREATE INDEX idx_message_conv ON message(conversation_id);
CREATE INDEX idx_kb_document_user ON kb_document(user_id);
CREATE INDEX idx_saved_insight_user ON saved_insight(user_id);
CREATE INDEX idx_shared_insight_token ON shared_insight(token);
CREATE INDEX idx_user_profile_user ON user_profile(user_id);
CREATE INDEX idx_memory_episode_user ON memory_episode(user_id);
CREATE INDEX idx_memory_episode_conv ON memory_episode(conversation_id);
CREATE INDEX idx_kbchunk_doc ON kb_chunk(doc_id);
CREATE INDEX idx_kbchunk_parent ON kb_chunk(parent_chunk_id);
CREATE INDEX idx_kbchunk_user ON kb_chunk(user_id);
CREATE INDEX idx_kbchunk_vec ON kb_chunk
    USING hnsw (embedding vector_cosine_ops) WHERE is_retrievable;
CREATE INDEX idx_kbchunk_fts ON kb_chunk
    USING gin (to_tsvector('simple', content_tokens));
