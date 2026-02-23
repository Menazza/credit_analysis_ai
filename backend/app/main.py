from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api.routes import auth, companies, documents, portfolios, reviews, export, monitoring, exceptions, mappings
from app.db.session import engine
from app.models import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure DB exists (tables created via Alembic)
    yield
    # Shutdown
    await engine.dispose()


app = FastAPI(
    title="Credit Analysis AI",
    description="Bank-grade corporate credit review platform",
    version="1.0.0",
    lifespan=lifespan,
)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(companies.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(portfolios.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(monitoring.router, prefix="/api")
app.include_router(mappings.router, prefix="/api")
app.include_router(exceptions.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
