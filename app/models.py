"""应用层（读写）数据模型：用户 / 会话 / 消息 / 知识库文档。

与只读分析库（dim_*/fact_*，仅供 Text2SQL 查询）分开存放在 APP_DATABASE_URL。
所有归属用户的数据都带 user_id 外键，落实技术设计第 8 节的用户隔离。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text, Boolean, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # bcrypt 哈希，绝不存明文
    nickname: Mapped[Optional[str]] = mapped_column(String(64))
    role: Mapped[Optional[str]] = mapped_column(String(16), default="user")        # 'user' / 'admin'
    disabled: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)        # 禁用后不能登录
    token_version: Mapped[Optional[int]] = mapped_column(Integer, default=0)        # P1 FIX: 改密码后自增，使旧 JWT 失效
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)  # 归属用户
    title: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Message(Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversation.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)  # 冗余便于过滤
    role: Mapped[str] = mapped_column(String(16), nullable=False)            # 'user' / 'assistant'
    content: Mapped[str] = mapped_column(Text, default="")
    intent: Mapped[Optional[str]] = mapped_column(String(16))                # sql / rag / hybrid / clarify / chat
    sql_text: Mapped[Optional[str]] = mapped_column(Text)                    # 助手消息的生成 SQL（可溯源）
    result_meta: Mapped[Optional[str]] = mapped_column(Text)                 # JSON：图表描述符/列+行/引用/trace，供历史会话还原图表&引用
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class KbDocument(Base):
    __tablename__ = "kb_document"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # NULL = 系统公共知识；非 NULL = 用户私有知识。检索层始终取“公共 + 当前用户”。
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ready")         # parsing/ready/failed
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # —— RAG/MinerU 入库扩展列（与生产 PG schema 对齐，均 nullable）——
    file_type: Mapped[Optional[str]] = mapped_column(String(16))             # pdf/html/text
    source_uri: Mapped[Optional[str]] = mapped_column(String(512))           # MinIO 对象路径
    title: Mapped[Optional[str]] = mapped_column(String(256))
    chunk_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)         # 软删除（重传旧版本）

class SavedInsight(Base):
    """收藏看板：用户把某条结果「收藏」下来的快照（图表描述符/列行/引用/SQL 等）。"""
    __tablename__ = "saved_insight"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255))
    question: Mapped[Optional[str]] = mapped_column(Text)
    intent: Mapped[Optional[str]] = mapped_column(String(16))            # sql / rag / hybrid
    payload: Mapped[Optional[str]] = mapped_column(Text)                 # JSON 快照（columns/rows/chart/insight/citations/sql）
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SharedInsight(Base):
    """一键分享：只读公开快照，凭 token 免登录访问（/api/public/share/{token}）。"""
    __tablename__ = "shared_insight"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)  # 创建者（可空）
    title: Mapped[Optional[str]] = mapped_column(String(255))
    question: Mapped[Optional[str]] = mapped_column(Text)
    intent: Mapped[Optional[str]] = mapped_column(String(16))
    payload: Mapped[Optional[str]] = mapped_column(Text)                 # JSON 快照（同上）
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserProfile(Base):
    """长期记忆 L3：结构化用户画像（偏好品牌、默认时间范围、输出风格等）。
    每个 key 一行，衰减机制控制过期。"""
    __tablename__ = "user_profile"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_profile_uid_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class MemoryEpisode(Base):
    """长期记忆 L2：会话结束时 LLM 提炼的摘要（关键词匹配召回相关历史）。"""
    __tablename__ = "memory_episode"
    __table_args__ = (UniqueConstraint("user_id", "conversation_id", name="uq_episode_uid_conv"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversation.id"), index=True, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    entities_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# 注意：kb_chunk（含 vector(1024)）不进 ORM Base——SQLite 建不了向量列。
# RAG 的 kb_chunk 读写一律走 app/rag/pg.py 的 psycopg 原生 SQL（仅 PostgreSQL）。
