from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.takeoff import router as takeoff_router
from app.core.tracing import langfuse


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Traces are sent in batches; send the last ones before the server stops.
    langfuse.shutdown()


app = FastAPI(lifespan=lifespan)

app.include_router(takeoff_router)

@app.get("/")
def home():
    return {
        "message":"AI Takeoff Backend Running"
    }