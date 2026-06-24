from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, teams
from app.database import engine, Base
from app.config import settings
from app.models import team, user

app = FastAPI(
    title="AI Sales Pipeline Agent",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# routers
app.include_router(auth.router)
app.include_router(teams.router)


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}