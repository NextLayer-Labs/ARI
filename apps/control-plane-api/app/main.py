from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.api.runs import router as runs_router
from app.api.inventory import router as inventory_router
from app.api.returns import router as returns_router
from app.settings import settings

app = FastAPI(title="NextLayer Control Plane", version="0.1.0")

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True, "service": "control-plane"}

app.include_router(api_router, prefix="/api")
app.include_router(runs_router)
app.include_router(inventory_router)
app.include_router(returns_router)

