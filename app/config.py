"""环境配置：集中读取 .env，便于切换模型 / 数据库。"""
import os
from dotenv import load_dotenv

load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bi_demo.db")
MAX_SQL_RETRY = int(os.getenv("MAX_SQL_RETRY", "2"))

# Text2SQL 语义自校验（§4.6）：SQL 能跑通 ≠ 语义对（"能跑但答非所问"是重试环救不了的那 ~22%）。
# 开启后：SQL 执行成功 → 让 LLM 核对"结果是否真的回答了问题(口径/过滤/聚合)" → 不匹配且仍有重试预算
# 则把原因回喂 fix_sql 重生成。代价 = 每条成功的数据查询多 1 次 LLM 调用（+延迟/成本）；
# **FAIL-OPEN**：校验自身异常一律放行，绝不比不校验更差。demo 想要快可设 SEMANTIC_CHECK=off。
SEMANTIC_CHECK = os.getenv("SEMANTIC_CHECK", "on").lower() in ("1", "true", "on", "yes")

# 应用层（读写）库：用户/会话/消息/知识库元数据。
# 与只读分析库 DATABASE_URL（Text2SQL 只查不写）分开，避免把可写表混进只读分析库。
# 生产：PostgreSQL（与 pgvector 同栈）；本地：单独 SQLite 文件 app.db。
APP_DATABASE_URL = os.getenv("APP_DATABASE_URL", "sqlite:///app.db")

# JWT 鉴权：密钥只放 .env，绝不入库/提交。
JWT_SECRET = os.getenv("JWT_SECRET", "dev-insecure-change-me")
JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", "7"))
JWT_ALGORITHM = "HS256"

# CORS 放行来源：dev 默认 "*"；生产收紧到正式域名（逗号分隔，如 https://chemirror.example.com）。
CORS_ALLOW_ORIGINS = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()]

# ============================================================
# RAG 离线入库管线（PRD-2 §5）配置
# ============================================================
# 向量库必须用 PostgreSQL + pgvector（SQLite 存不了 vector(1024)）。
# RAG 的 kb_document/kb_chunk 一律落这里；与登录模块的 APP_DATABASE_URL 解耦——
# 即使 app 仍跑 SQLite(app.db)，RAG 也独立连 PG。生产把两者都指向 PG 即统一。
RAG_DATABASE_URL = os.getenv(
    "RAG_DATABASE_URL",
    "postgresql://app_rw:app_rw_pass_change_me@localhost:5432/app",  # psycopg 原生串(非 +psycopg)
)

# RAG 存储后端：'local'(默认) = SQLite+numpy 本地向量库（免 pgvector/Docker，开箱即用）；
# 'pg' = PostgreSQL+pgvector（生产/全栈）。两者接口一致（pg.py ↔ local_store.py），切换不动检索逻辑。
RAG_BACKEND = os.getenv("RAG_BACKEND", "local").lower()
# 本地向量库文件（RAG_BACKEND=local 时用）。种子语料 + 用户上传都落这里。
LOCAL_KB_PATH = os.getenv("LOCAL_KB_PATH", "data/local_kb.sqlite")

# 对象存储（MinIO）：上传/爬取的原始文件先落 MinIO，再异步解析。
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "carmirror-admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minio_pass_change_me_8+")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_BUCKET_UPLOADS = os.getenv("MINIO_BUCKET_UPLOADS", "kb-uploads")

# Celery 异步（解析/切块/向量化耗时，放后台 worker）
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")  # dev 容器未启用密码
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

# —— Embedding 模型（§5.8 版本一致性：模型名/版本入 config；换模型必须全量重建索引）——
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-large-zh-v1.5")
EMBED_MODEL_VERSION = os.getenv("EMBED_MODEL_VERSION", "bge-large-zh-v1.5")  # 写进每个 chunk 血缘/校验
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))                              # 必须与 kb_chunk.embedding 维度一致
EMBED_MAX_TOKENS = 512          # BGE-large-zh 硬上限：超了截断丢语义（§5.3）

# —— 切块参数（§5.3，按 token 不按字符）——
CHUNK_CHILD_TOKENS = int(os.getenv("CHUNK_CHILD_TOKENS", "280"))   # 子块目标 ~250-300 token（留余量给标题前缀）
CHUNK_PARENT_TOKENS = int(os.getenv("CHUNK_PARENT_TOKENS", "900")) # 父块=完整小节 ~800-1000 token
CHUNK_OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", "64"))# 相邻子块 overlap ~50-80 token

# —— 在线检索（§5.4 / §5.4.1）——
RERANK_MODEL_NAME = os.getenv("RERANK_MODEL_NAME", "models/bge-reranker-base")  # 本地优先；缺则降级 RRF
RECALL_VEC_K = int(os.getenv("RECALL_VEC_K", "20"))     # 向量召回候选数
RECALL_KW_K = int(os.getenv("RECALL_KW_K", "20"))       # 关键词(全文)召回候选数
RRF_K = int(os.getenv("RRF_K", "60"))                   # RRF 融合常数（经验值 60）
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "8"))      # 重排后保留的子块数
CONTEXT_TOKEN_BUDGET = int(os.getenv("CONTEXT_TOKEN_BUDGET", "3000"))  # 父块上下文 token 预算（情形C）
MAX_PARENTS = int(os.getenv("MAX_PARENTS", "5"))        # 父块数上限（防 lost-in-the-middle）
RERANK_SCORE_MIN = float(os.getenv("RERANK_SCORE_MIN", "0.30"))  # 最高重排分低于此 → 判无依据（防幻觉）
NLU_CONFIG_PATH = os.getenv("NLU_CONFIG_PATH", "config/nlu.yaml")
AGENTS_CONFIG_PATH = os.getenv("AGENTS_CONFIG_PATH", "config/agents.yaml")
