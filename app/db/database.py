import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import event
from app.config import get_settings
from app.db.models import Base

logger = logging.getLogger(__name__)

settings = get_settings()

# Engine creation
# For SQLite, check if database url begins with sqlite
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=connect_args,
)

# Enable foreign keys for SQLite
if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    """Create all tables in the database and apply lightweight schema migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        if settings.DATABASE_URL.startswith("sqlite"):
            def migrate_sqlite_columns(sync_conn):
                cursor = sync_conn.connection.cursor()
                cursor.execute("PRAGMA table_info(crawl_jobs);")
                columns = [row[1] for row in cursor.fetchall()]
                if columns and "linkedin_found" not in columns:
                    cursor.execute("ALTER TABLE crawl_jobs ADD COLUMN linkedin_found INTEGER DEFAULT 0;")
                cursor.close()

            await conn.run_sync(migrate_sqlite_columns)

    logger.info("Database initialized successfully.")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
