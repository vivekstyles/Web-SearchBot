import uuid
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    String,
    Text,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    robots_txt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    robots_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    crawl_delay: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    start_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)  # queued, running, completed, failed, stopped
    max_pages: Mapped[int] = mapped_column(Integer, default=500)
    max_depth: Mapped[int] = mapped_column(Integer, default=5)
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0)
    pages_failed: Mapped[int] = mapped_column(Integer, default=0)
    emails_found: Mapped[int] = mapped_column(Integer, default=0)
    phones_found: Mapped[int] = mapped_column(Integer, default=0)
    linkedin_found: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    pages: Mapped[List["Page"]] = relationship("Page", back_populates="crawl_job", cascade="all, delete-orphan")
    contact_sources: Mapped[List["ContactSource"]] = relationship("ContactSource", back_populates="crawl_job", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    crawl_job_id: Mapped[str] = mapped_column(String(36), ForeignKey("crawl_jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    url: Mapped[str] = mapped_column(String(2048), index=True, nullable=False)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    response_time_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    crawl_job: Mapped["CrawlJob"] = relationship("CrawlJob", back_populates="pages")
    contact_sources: Mapped[List["ContactSource"]] = relationship("ContactSource", back_populates="page", cascade="all, delete-orphan")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    type: Mapped[str] = mapped_column(String(16), index=True, nullable=False)  # email, phone, linkedin
    value: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(512), index=True, nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    sources: Mapped[List["ContactSource"]] = relationship("ContactSource", back_populates="contact", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("type", "normalized_value", name="uq_contact_type_normalized"),
    )


class ContactSource(Base):
    __tablename__ = "contact_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id", ondelete="CASCADE"), index=True, nullable=False)
    page_id: Mapped[str] = mapped_column(String(36), ForeignKey("pages.id", ondelete="CASCADE"), index=True, nullable=False)
    crawl_job_id: Mapped[str] = mapped_column(String(36), ForeignKey("crawl_jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    context: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="body")  # body, header, footer, address, mailto, tel, metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    contact: Mapped["Contact"] = relationship("Contact", back_populates="sources")
    page: Mapped["Page"] = relationship("Page", back_populates="contact_sources")
    crawl_job: Mapped["CrawlJob"] = relationship("CrawlJob", back_populates="contact_sources")

    __table_args__ = (
        UniqueConstraint("contact_id", name="uq_contact_source_contact"),
    )
