from __future__ import annotations

from collections.abc import Generator

from forgegraph.core.settings import Settings
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


def build_engine(settings: Settings):
    connect_args = {"password": settings.database_password} if settings.database_password else {}
    return create_engine(
        settings.database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_recycle=1800,
        future=True,
    )


class Database:
    def __init__(self, settings: Settings):
        self.engine = build_engine(settings)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    def create_schema(self) -> None:
        from forgegraph.db.base import Base

        Base.metadata.create_all(self.engine)

    def ping(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def session(self) -> Generator[Session, None, None]:
        db = self.session_factory()
        try:
            yield db
        finally:
            db.close()
