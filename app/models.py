from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class LeadStatus(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    NOT_RELEVANT = "not_relevant"
    SPAM = "spam"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    normalized_text: Mapped[str] = mapped_column(Text)
    original_text: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, index=True)
    reasons: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default=LeadStatus.NEW.value, index=True)
    sender_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sender_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    sources: Mapped[list[LeadSource]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )


class LeadSource(Base):
    __tablename__ = "lead_sources"
    __table_args__ = (UniqueConstraint("chat_id", "message_id", name="uq_source_message"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    chat_title: Mapped[str] = mapped_column(String(255))
    chat_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message_id: Mapped[int] = mapped_column(Integer)
    message_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    lead: Mapped[Lead] = relationship(back_populates="sources")
