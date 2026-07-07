from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.routers import auth, teams, onboarding, leads, emails, meetings, proposals, knowledge_base, chat
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
    allow_origins=settings.frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# routers
app.include_router(auth.router)
app.include_router(teams.router)
app.include_router(onboarding.router)
app.include_router(leads.router)
app.include_router(emails.router)
app.include_router(meetings.router)
app.include_router(proposals.router)
app.include_router(knowledge_base.router)
app.include_router(chat.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": "Request failed",
            "data": None,
            "error": exc.detail,
        },
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": "Validation failed",
            "data": None,
            "error": jsonable_encoder(exc.errors()),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Internal server error",
            "data": None,
            "error": str(exc) if settings.app_env == "development" else "Internal server error",
        },
    )


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/health")
async def health():
    return {
        "success": True,
        "message": "API is healthy",
        "data": {"status": "ok", "env": settings.app_env},
        "error": None,
    }
