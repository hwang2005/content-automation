import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


def utcnow():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    writing_guide: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    formats: Mapped[list["ArticleFormat"]] = relationship(passive_deletes=True)


class ArticleFormat(Base):
    __tablename__ = "article_formats"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    structure: Mapped[str] = mapped_column(Text)
    writing_guide: Mapped[str] = mapped_column(Text, default="")
    samples: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    detection_keywords: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GeneratedPost(Base):
    __tablename__ = "generated_posts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    format_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("article_formats.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(30))
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_text: Mapped[str] = mapped_column(Text)
    source_title: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[dict]] = mapped_column(JSON_DOCUMENT, default=list)
    facts: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    selected_format_name: Mapped[str] = mapped_column(String(120))
    selection_reason: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    format_snapshot: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    generated_content: Mapped[str] = mapped_column(Text)
    original_content: Mapped[str] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    additional_instructions: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(120))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
