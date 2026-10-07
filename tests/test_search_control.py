"""
Tests for the Stop-search support (src/services/search_control.py).
The model is replaced by a fake, so no Ollama is needed.
"""
from unittest.mock import MagicMock

import pytest

from src.services import ai_service
from src.services.search_control import CancelToken, CancellableAIService, SearchCancelled


def _client(reply="Item: brick\nCategory: construction_waste"):
    client = MagicMock()
    client.generate.return_value = reply
    return client


def test_category_id_is_remembered_after_a_successful_check():
    service = CancellableAIService(CancelToken(), model_client=_client())
    result = service.process_recycling_query("brick")
    assert result.disposal_category == "Construction and renovation waste"
    assert service.category_id == "construction_waste"


def test_garden_waste_is_recognised():
    service = CancellableAIService(
        CancelToken(), model_client=_client("Item: branches\nCategory: garden_waste")
    )
    service.process_recycling_query("branches")
    assert service.category_id == "garden_waste"


def test_cancelled_before_start_never_calls_the_model():
    token = CancelToken()
    token.cancel()
    client = _client()
    service = CancellableAIService(token, model_client=client)
    with pytest.raises(SearchCancelled):
        service.process_recycling_query("brick")
    assert client.generate.call_count == 0


def test_cancelled_while_the_model_runs_records_nothing(monkeypatch):
    token = CancelToken()
    client = MagicMock()

    def slow_generate(prompt):
        token.cancel()  # the user presses Stop while the model is still busy
        return "Item: brick\nCategory: construction_waste"

    client.generate.side_effect = slow_generate
    recorded = []
    monkeypatch.setattr(ai_service, "record_entry", lambda *a, **k: recorded.append(a))

    service = CancellableAIService(token, model_client=client)
    ai_service.generate_recycling_response("brick", service=service)

    assert recorded == []
    assert service.category_id is None


def test_a_normal_check_is_still_recorded(monkeypatch):
    recorded = []
    monkeypatch.setattr(ai_service, "record_entry", lambda *a, **k: recorded.append(a))
    service = CancellableAIService(CancelToken(), model_client=_client())
    text = ai_service.generate_recycling_response("brick", service=service)
    assert "Construction and renovation waste" in text
    assert len(recorded) == 1
