from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.jobs import CardWorkflowInput
from app.temporal import client as temporal_client

PHONE = "+7 926 555-14-08"


class StartCapture:
    """Stands in for the Temporal client: keeps each started input"""

    def __init__(self) -> None:
        self.inputs: list[CardWorkflowInput] = []

    async def start_workflow(
        self, workflow: object, workflow_input: CardWorkflowInput, **_: object
    ) -> None:
        """Keep the workflow input"""
        self.inputs.append(workflow_input)


async def test_supplier_text_enters_the_workflow_masked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The workflow input, kept in its history, holds placeholders"""
    capture = StartCapture()

    async def get_capture() -> StartCapture:
        return capture

    monkeypatch.setattr(temporal_client, "get_temporal_client", get_capture)
    monkeypatch.setattr(
        temporal_client,
        "get_settings",
        lambda: SimpleNamespace(
            card_confidence_threshold=0.7, temporal_task_queue="cards"
        ),
    )

    await temporal_client.start_card_workflow(
        uuid4(), f"Blender MixerPro 800 W. Call {PHONE}."
    )

    [workflow_input] = capture.inputs
    assert workflow_input.supplier_text == (
        "Blender MixerPro 800 W. Call [PHONE_1]."
    )
