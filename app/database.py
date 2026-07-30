from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


# base class all models inherit from
class Base(DeclarativeBase):
    pass


# async engine — handles the actual connection to PostgreSQL
connect_args = {"ssl": "require"} if settings.app_env not in {"development", "test"} else {}

engine = create_async_engine(
    settings.database_url,
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
