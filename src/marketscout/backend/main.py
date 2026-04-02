"""MarketScout FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import marketscout.config  # noqa: F401 — triggers load_dotenv() at server startup
from marketscout.backend.nl2sql import router as nl2sql_router

app = FastAPI(
    title="MarketScout API",
    version="2.0",
    description="API layer for MarketScout opportunity mapping and NL2SQL queries.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(nl2sql_router, prefix="/api")


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "MarketScout API is running", "version": "2.0"}
