from fastapi import FastAPI

from backend.api.routes import router


app = FastAPI(
    title="GridWise Copilot"
)


app.include_router(router)


@app.get("/")
def home():

    return {
        "message": "GridWise Copilot API running"
    }