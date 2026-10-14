"""Engine async + session factory (pooling configurado desde el día 1).

C-02: la identidad vive en `app/core/dependencies.py` (`get_current_user`
JWT/RBAC); sin RLS por decisión de diseño §8 (matriz en capa de aplicación).
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
