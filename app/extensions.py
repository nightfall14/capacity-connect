"""Database primitives used by the FastAPI application."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import Config


class Base(DeclarativeBase):
    pass


engine = create_engine(
    Config.DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

