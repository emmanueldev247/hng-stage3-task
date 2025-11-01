from fastapi import APIRouter

router = APIRouter()

@router.get("/health", tags=["system"])
def health():
    return {"status": "ok"}
