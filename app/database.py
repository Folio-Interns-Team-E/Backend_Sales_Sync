from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


# Base class that all models inherit from
class Base(DeclarativeBase):
    pass


# Only enable SSL in production
connect_args = {}

if settings.app_env == "production":
    import ssl
    connect_args["ssl"] = ssl.create_default_context()


# Async engine — handles the actual connection to PostgreSQL
engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",  # logs SQL queries in development
    connect_args=connect_args,
)


# Session factory
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# Dependency — used in routers via Depends(get_db)
async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise