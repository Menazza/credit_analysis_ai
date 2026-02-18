from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import get_settings

Base = declarative_base()
_settings = get_settings()
_connect_args = {}
if _settings.database_require_ssl:
    _connect_args["ssl"] = True
engine = create_async_engine(
    _settings.database_url,
    connect_args=_connect_args,
    echo=_settings.environment == "development",
)
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
