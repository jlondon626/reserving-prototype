"""A small FastAPI service for the reserving prototype."""

from typing import Annotated

from fastapi import FastAPI, Query

app = FastAPI(
    title="Reserving API",
    description="A simple API for testing the reserving prototype deployment.",
    version="0.1.0",
)


@app.get("/")
async def index() -> dict[str, str]:
    return {"message": "Reserving API is running."}


@app.get("/hello")
async def hello(
    name: Annotated[str, Query(min_length=1, max_length=100)] = "World",
) -> dict[str, str]:
    return {"message": f"Hello, {name}!"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
