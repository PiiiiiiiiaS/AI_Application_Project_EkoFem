from unittest.mock import MagicMock
import pytest

from src.config import config
from src.models.model_client import (
    ModelClientError,
    OllamaConnectionError,
    ModelNotFoundError,
)
from src.services.ai_service import (
    AIService,
    OutOfScopeInput,
    generate_response,
    generate_recycling_response,
    _parse_classification_response,
    _load_waste_categories,
)


def test_config_loading():
    """Verify that configuration settings load expected string values from environment or defaults."""
    assert config.ollama_base_url is not None
    assert config.model_name is not None
    assert isinstance(config.ollama_base_url, str)
    assert isinstance(config.model_name, str)


def test_empty_input_validation():
    """Verify that empty or whitespace inputs are rejected gracefully without invoking the model."""
    mock_client = MagicMock()
    service = AIService(model_client=mock_client)

    # Test empty string
    response_empty = service.process_message("")
    assert response_empty.success is False
    assert "Please enter a message" in response_empty.content
    assert mock_client.generate.call_count == 0

    # Test whitespace string
    response_spaces = service.process_message("   ")
    assert response_spaces.success is False
    assert mock_client.generate.call_count == 0


def test_successful_response_generation():
    """Verify that valid input invokes model client and returns the generated string response."""
    mock_client = MagicMock()
    mock_client.generate.return_value = "Hello! I am an AI assistant."
    service = AIService(model_client=mock_client)

    result_text = generate_response("Hello, AI", service=service)

    assert result_text == "Hello! I am an AI assistant."
    mock_client.generate.assert_called_once_with("Hello, AI")


def test_ollama_connection_error_handling():
    """Verify that Ollama connection failures produce a friendly application-level error message."""
    mock_client = MagicMock()
    mock_client.generate.side_effect = OllamaConnectionError("Connection refused at http://localhost:11434")
    service = AIService(model_client=mock_client)

    response = service.process_message("Test message")

    assert response.success is False
    assert "Could not connect to Ollama" in response.content
    assert "Connection refused" in response.error_message


def test_model_not_found_error_handling():
    """Verify that missing model exceptions are converted into controlled user messages."""
    mock_client = MagicMock()
    mock_client.generate.side_effect = ModelNotFoundError("Model llama3.2 not found locally")
    service = AIService(model_client=mock_client)

    response = service.process_message("Test message")

    assert response.success is False
    assert "configured AI model is unavailable" in response.content
    assert "llama3.2 not found" in response.error_message


# --- WasteBuddy-specific tests: grounding and classification logic ---


def test_parse_classification_response_falls_back_to_mixed_waste_for_invalid_category():
    """
    Verify that an unrecognized category id returned by the model is never trusted
    as-is. If the model answers with something that is not one of the known
    category ids, the parser must fall back to mixed_waste rather than passing
    an invalid category through to the user.
    """
    categories = _load_waste_categories()
    raw_response = "Item: something odd\nCategory: not_a_real_category"

    item_name, matched_category = _parse_classification_response(raw_response, categories)

    assert item_name == "something odd"
    assert matched_category["id"] == "mixed_waste"


def test_process_recycling_query_grounds_disposal_facts_from_dataset():
    """
    Verify that disposal_category and recycled_into always come from
    data/finland_waste_categories.json, not from whatever text the model
    happens to return. The model is only trusted to pick a category id;
    every fact attached to that id must match the reference dataset exactly.
    """
    mock_client = MagicMock()
    mock_client.generate.return_value = "Item: glass jar\nCategory: glass"
    service = AIService(model_client=mock_client)

    result = service.process_recycling_query("glass jar")

    categories = _load_waste_categories()
    expected_category = next(cat for cat in categories if cat["id"] == "glass")

    assert result.identified_item == "glass jar"
    assert result.disposal_category == expected_category["name"]
    assert result.recycled_into == expected_category["recycled_into"]


def test_process_recycling_image_runs_vision_then_text_classification():
    """
    Verify the two-stage photo path: the vision model is called once, only to
    name the item, and the same text classification logic used for typed
    input is then reused to pick the category. This confirms the photo and
    text paths converge on one shared, tested classification step rather than
    the vision model making a disposal decision on its own.
    """
    mock_client = MagicMock()
    mock_client.generate_vision.return_value = "cardboard pizza box"
    mock_client.generate.return_value = "Item: cardboard pizza box\nCategory: cardboard"
    service = AIService(model_client=mock_client)

    result = service.process_recycling_image(b"fake-image-bytes")

    mock_client.generate_vision.assert_called_once()
    mock_client.generate.assert_called_once()
    assert result.disposal_category == "Cardboard / Carton"


# --- Off-topic handling tests (closes the gap evaluation case-12 flagged) ---


def test_parse_classification_response_returns_none_category_for_off_topic_sentinel():
    """
    Verify that the off_topic sentinel the model can return is recognized
    distinctly from an unrecognized category id: it must NOT fall back to
    mixed_waste, since that would silently force a genuinely unrelated
    question into a nonsensical disposal answer, exactly the gap the
    September 2026 evaluation round flagged in evaluation_results.md.
    """
    categories = _load_waste_categories()
    raw_response = "Item: not applicable\nCategory: off_topic"

    _, matched_category = _parse_classification_response(raw_response, categories)

    assert matched_category is None


def test_process_recycling_query_raises_out_of_scope_for_off_topic_input():
    """Verify the service layer raises OutOfScopeInput rather than returning a fabricated category."""
    mock_client = MagicMock()
    mock_client.generate.return_value = "Item: not applicable\nCategory: off_topic"
    service = AIService(model_client=mock_client)

    with pytest.raises(OutOfScopeInput):
        service.process_recycling_query("What is the capital of France?")


def test_generate_recycling_response_redirects_politely_for_off_topic_input():
    """
    End-to-end check of the fix for evaluation case-12: a question unrelated
    to waste sorting should get a friendly redirect, not a forced,
    nonsensical classification like "Mixed waste".
    """
    mock_client = MagicMock()
    mock_client.generate.return_value = "Item: not applicable\nCategory: off_topic"
    service = AIService(model_client=mock_client)

    result_text = generate_recycling_response("What is the capital of France?", service=service)

    assert "doesn't look like a waste item" in result_text.lower()
