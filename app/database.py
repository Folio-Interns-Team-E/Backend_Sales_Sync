from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings
from app.core.database_config import async_database_options


# base class all models inherit from
class Base(DeclarativeBase):
    pass


# async engine — handles the actual connection to PostgreSQL
database_url, connect_args = async_database_options(settings.database_url, settings.database_ssl_mode, settings.app_env)

engine = create_async_engine(
    database_url,
    echo=settings.app_env == "development",  # logs SQL queries in dev only
    pool_pre_ping=True,     # 🔥 FIX 1
    pool_recycle=300,  
    connect_args=connect_args,

)

# session factory
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


# dependency — used in routers via Depends(get_db)
async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
