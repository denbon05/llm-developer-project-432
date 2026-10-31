from fastapi import APIRouter

from app.schemas.cards import CardPreview, CardRequest
from app.services.pipeline import preview_card

CARDS_PATH = "/cards"

router = APIRouter(tags=["cards"])


@router.post(CARDS_PATH)
async def create_card_draft(body: CardRequest) -> CardPreview:
    """Return a card draft for the supplier text"""
    return await preview_card(body.supplier_text)
