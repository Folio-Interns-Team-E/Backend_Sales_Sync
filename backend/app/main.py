from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.routers import auth, teams, onboarding
from app.routers.leads import router as leads_router
from app.database import engine, Base
from app.config import settings

# Import ALL models so SQLAlchemy creates every table on startup
from app.models import team, user, icp  # noqa: F401
from app.models.lead import Lead         # noqa: F401

app = FastAPI(
    title="SalesSync AI — Backend",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",   # Vite default
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(teams.router)
app.include_router(onboarding.router)
app.include_router(leads_router)

# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_subject TEXT"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_body TEXT"))
        await conn.run_sync(Base.metadata.create_all)


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}


@app.get("/")
async def root():
    return {
        "message": "SalesSync AI backend is running",
        "health": "/health",
        "docs": "/docs",
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)