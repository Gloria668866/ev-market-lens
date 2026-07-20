-- ============================================================
-- 车市镜 · 分析库 schema（结构化脑 Text2SQL 用）
-- 方言：PostgreSQL（生产）；括号注明 SQLite（本地 demo）差异
-- 字段依据：data/probe/数据源字段清单.md —— 懂车帝销量榜 API 实测字段
-- 设计方法：Kimball 维度建模（业务问题→度量→粒度→维度+事实），见 PRD-1 第 7 章
-- 重要：本榜单为全国口径，实测无分地区数据 → 故意不建 dim_region 空表
-- ============================================================

-- ---------- 维度：品牌 ----------
CREATE TABLE dim_brand (
    brand_id        INTEGER PRIMARY KEY,            -- 懂车帝 brand_id（实测）
    brand_name      VARCHAR(64) NOT NULL,           -- 如「吉利银河」
    sub_brand_id    INTEGER,
    sub_brand_name  VARCHAR(64),
    country_type    VARCHAR(16),                    -- 自主/合资/进口（enrich，先 NULL）
    is_new_force    BOOLEAN,                        -- 是否新势力（enrich，先 NULL）
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------- 维度：车系 ----------
CREATE TABLE dim_series (
    series_id       INTEGER PRIMARY KEY,            -- 懂车帝 series_id（实测）
    series_name     VARCHAR(128) NOT NULL,          -- 如「星愿」「小米SU7」
    brand_id        INTEGER REFERENCES dim_brand(brand_id),
    sub_brand_id    INTEGER,
    segment         VARCHAR(32),                    -- 级别 中型SUV/紧凑型车…（口碑页 car_type 回填）
    powertrain      VARCHAR(32),                    -- 动力 纯电/插混/增程（由 new_energy_type 推断）
    endurance_km    INTEGER,                         -- 续航上限(km)，口碑页 pc_config.recharge_mileage 回填
    guide_price_min NUMERIC(8,2),                   -- 当前指导价下限(万元) 快照
    guide_price_max NUMERIC(8,2),                   -- 当前指导价上限(万元) 快照
    image_url       VARCHAR(256),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------- 维度：月份（销量榜为月粒度）----------
CREATE TABLE dim_date (
    date_id   INTEGER PRIMARY KEY,                  -- YYYYMM，如 202605
    year      SMALLINT NOT NULL,
    month     SMALLINT NOT NULL,
    quarter   SMALLINT NOT NULL,
    ym        CHAR(7)  NOT NULL                     -- '2026-05'
);

-- ---------- 事实：销量榜（粒度 = 车系 × 月 × 能源类型）----------
CREATE TABLE fact_sales_rank (
    id              BIGSERIAL PRIMARY KEY,          -- SQLite: INTEGER PRIMARY KEY AUTOINCREMENT
    series_id       INTEGER REFERENCES dim_series(series_id),
    date_id         INTEGER REFERENCES dim_date(date_id),
    new_energy_type SMALLINT,                       -- 0全部/1纯电/2插混/3增程（实测请求参数）
    rank_type       SMALLINT,                       -- 榜单类型 rank_data_type
    rank            INTEGER,                        -- 本期排名（实测 rank）
    last_rank       INTEGER,                        -- 上期排名（实测 last_rank，算环比趋势）
    volume          INTEGER,                        -- 销量（实测 count，核心度量）
    source          VARCHAR(32) DEFAULT 'dongchedi',
    source_url      VARCHAR(512),                   -- 血缘：原始接口 URL
    crawl_time      TIMESTAMP,
    etl_version     VARCHAR(16),
    UNIQUE (series_id, date_id, new_energy_type, rank_type)   -- 增量去重键
);

-- ---------- 事实：报价（粒度 = 车系 × 快照日）----------
CREATE TABLE fact_price (
    id                BIGSERIAL PRIMARY KEY,
    series_id         INTEGER REFERENCES dim_series(series_id),
    date_id           INTEGER REFERENCES dim_date(date_id),
    snapshot_date     DATE,
    guide_price_min   NUMERIC(8,2),                 -- 实测 min_price（万元）
    guide_price_max   NUMERIC(8,2),                 -- 实测 max_price
    price_text        VARCHAR(64),                  -- 实测 price，如「5.98-8.98万」
    dealer_price_text VARCHAR(64),                  -- 实测 dealer_price
    has_dealer_price  BOOLEAN,                       -- 实测 has_dealer_price
    descender_price   NUMERIC(8,2),                 -- 实测 descender_price（降价幅度）
    source            VARCHAR(32) DEFAULT 'dongchedi',
    source_url        VARCHAR(512),
    crawl_time        TIMESTAMP,
    etl_version       VARCHAR(16)
);

-- ---------- 事实：口碑（粒度 = 车系 × 快照日）----------
CREATE TABLE fact_review (
    id            BIGSERIAL PRIMARY KEY,
    series_id     INTEGER REFERENCES dim_series(series_id),
    date_id       INTEGER REFERENCES dim_date(date_id),
    snapshot_date DATE,
    review_count  INTEGER,                          -- 实测 car_review_count
    score         NUMERIC(3,1),                     -- 评分（销量接口恒为0 → 口碑专用接口补，先 NULL）
    sentiment     VARCHAR(8),                       -- 正/中/负（评论文本情感分析后补）
    source        VARCHAR(32) DEFAULT 'dongchedi',
    source_url    VARCHAR(512),
    crawl_time    TIMESTAMP,
    etl_version   VARCHAR(16)
);

-- ---------- 索引 ----------
CREATE INDEX idx_sales_series_date ON fact_sales_rank(series_id, date_id);
CREATE INDEX idx_sales_date        ON fact_sales_rank(date_id);
CREATE INDEX idx_price_series      ON fact_price(series_id);
CREATE INDEX idx_review_series     ON fact_review(series_id);

-- ============================================================
-- 知识库（非结构化脑 RAG 用）的 kb_chunk（含 pgvector 向量列）见 PRD-2 第 6 章。
-- ============================================================

-- ============================================================
-- 应用层（读写库）：用户 / 会话 / 消息 / 知识库文档
-- 重要：这些是【读写】表，与上面只读的分析库（dim_*/fact_*）分库存放——
--   分析库 = 只读账号，仅供 Text2SQL 查询；应用库 = 读写，存用户态数据。
--   本地用单独 SQLite（app.db，由 SQLAlchemy 模型 app/models.py 建表）；
--   生产用 PostgreSQL（与 pgvector 同栈）。方言：PostgreSQL。
-- 隔离（PRD-2 §17.3）：归属用户的数据都带 user_id 外键，按 user_id 过滤。
-- ============================================================

-- ---------- 用户 ----------
CREATE TABLE users (
    id             BIGSERIAL PRIMARY KEY,           -- SQLite: INTEGER PRIMARY KEY AUTOINCREMENT
    username       VARCHAR(64) UNIQUE NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,           -- bcrypt 哈希，绝不存明文
    nickname       VARCHAR(64),
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at  TIMESTAMP
);

-- ---------- 会话 ----------
CREATE TABLE conversation (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),   -- 归属用户
    title       VARCHAR(255),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------- 消息 ----------
CREATE TABLE message (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  BIGINT NOT NULL REFERENCES conversation(id),
    user_id          BIGINT NOT NULL REFERENCES users(id),  -- 冗余便于按用户过滤
    role             VARCHAR(16) NOT NULL,                  -- 'user' / 'assistant'
    content          TEXT,
    intent           VARCHAR(16),                           -- sql / doc / chat
    sql_text         TEXT,                                  -- 助手消息生成的 SQL（可溯源）
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------- 知识库文档（元数据；切片/向量见 kb_chunk）----------
CREATE TABLE kb_document (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),   -- 归属用户
    filename    VARCHAR(255) NOT NULL,
    status      VARCHAR(16) DEFAULT 'ready',            -- parsing / ready / failed
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_conversation_user ON conversation(user_id);
CREATE INDEX idx_message_user      ON message(user_id);
CREATE INDEX idx_kb_document_user  ON kb_document(user_id);

-- ============================================================
-- Performance indexes (append after table creation)
-- ============================================================
-- CREATE INDEX idx_fact_sales_date ON fact_sales_rank(date_id);
-- CREATE INDEX idx_fact_sales_series ON fact_sales_rank(series_id);
-- CREATE INDEX idx_fact_sales_type ON fact_sales_rank(new_energy_type);
-- CREATE INDEX idx_fact_sales_series_date ON fact_sales_rank(series_id, date_id);  -- composite for joins
-- CREATE INDEX idx_dim_series_brand ON dim_series(brand_id);
-- CREATE INDEX idx_message_conv ON message(conversation_id);
-- CREATE INDEX idx_message_user ON message(user_id);
