from fastapi import FastAPI
from app.api.health import router as health_router
from app.api.a2a_routes import router as a2a_router
from app.api.manifest import router as manifest_router
from app.utils.aliases import refresh_aliases
from app.core.logger import logger

app = FastAPI(title="CryptoSage A2A (FastAPI)", version="1.0.0")

# routers
app.include_router(health_router, prefix="")
app.include_router(a2a_router, prefix="")
app.include_router(manifest_router, prefix="")

@app.get("/")
def root():
    return {"name": "CryptoSage A2A", "status": "ok"}

try:
    refresh_aliases()
except Exception as e:
    logger.error(f"[create_app] failed to warm alias cache: {e}", exc_info=True)
