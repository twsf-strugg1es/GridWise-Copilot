from fastapi import FastAPI
from backend.api.routes import router


app = FastAPI(
    title="GridMind AI",
    description="LLM assisted campus energy optimization API"
)


app.include_router(router)