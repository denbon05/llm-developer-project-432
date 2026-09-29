from fastapi import APIRouter

from app.schemas.cards import CardPreview, CardRequest
from app.services.pipeline import run_pipeline

CARDS_PATH = "/cards"

router = APIRouter(tags=["cards"])


@router.post(CARDS_PATH)
async def create_card_draft(body: CardRequest) -> CardPreview:
    """Return a card draft for the supplier text"""
    return await run_pipeline(body.supplier_text)
