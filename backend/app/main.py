import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.db import Base, engine
from app import models  # noqa: F401  (registers tables)
from app.routers import auth, chat, documents, stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app.http")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Enterprise Intelligence Platform", version="1.0.0",
              description="Document intelligence, advanced RAG, LangGraph agent, Gemini LLMs with fallback.",
              lifespan=lifespan)

origins = {settings.FRONTEND_URL.rstrip("/"), "http://localhost:5173", "http://127.0.0.1:5173"}
app.add_middleware(CORSMiddleware, allow_origins=list(origins), allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def access_log(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    logger.info("%s %s -> %s (%d ms)", request.method, request.url.path, response.status_code,
                (time.perf_counter() - t0) * 1000)
    return response


app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(stats.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.get("/health/deps", tags=["health"])
def health_deps():
    from app.services import vectorstore
    return {"gemini_key_set": bool(settings.GEMINI_API_KEY), "primary_model": settings.PRIMARY_MODEL,
            "fallback_model": settings.FALLBACK_MODEL, "weaviate_ready": vectorstore.ping()}
