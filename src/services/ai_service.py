import json
from pathlib import Path
from typing import Optional
from src.models.model_client import (
    OllamaModelClient,
    ModelClientError,
    OllamaConnectionError,
    ModelNotFoundError,
)
from src.schemas.responses import UserRequest, AIResponse, RecyclingResponse
from src.services.history import record_entry

WASTE_DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "finland_waste_categories.json"


class OutOfScopeInput(Exception):
    """Raised when the model determines the input does not describe a waste item at all."""
    pass


def _load_waste_categories() -> list[dict]:
    """Loads Finland's waste category reference data — the single source of truth for disposal facts."""
    with open(WASTE_DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["categories"]


def _build_classification_prompt(item_description: str, categories: list[dict]) -> str:
    """
    Builds a prompt that restricts the model to picking from a fixed, known
    list of categories, or flagging that the input is not a waste item at all.
    """
    category_lines = "\n".join(
        f"- {cat['id']}: {cat['name']} (includes: {', '.join(cat['belongs'])})"
        for cat in categories
    )
    return (
        "You are helping sort a waste item into Finland's official recycling categories.\n\n"
        f'Text describing what the user wants sorted: "{item_description}"\n\n'
        "Here are the only valid categories:\n"
        f"{category_lines}\n\n"
        "If the text above does not describe a physical waste item at all (for example, it is a "
        "question unrelated to waste sorting, a greeting, or random text), respond with EXACTLY "
        "these two lines instead:\n"
        "Item: not applicable\n"
        "Category: off_topic\n\n"
        "Otherwise, respond with EXACTLY two lines, nothing else:\n"
        "Item: <a short, clear name for the item>\n"
        "Category: <the single matching category id from the list above, exactly as written>"
    )


def _build_vision_classification_prompt(categories: list[dict]) -> str:
    """Builds a prompt asking the vision model to identify an item from a photo and classify it."""
    category_lines = "\n".join(
        f"- {cat['id']}: {cat['name']} (includes: {', '.join(cat['belongs'])})"
        for cat in categories
    )
    return (
        "Look at this image and identify the main waste item shown, then sort it into "
        "Finland's official recycling categories.\n\n"
        "Here are the only valid categories:\n"
        f"{category_lines}\n\n"
        "Respond with EXACTLY two lines, nothing else:\n"
        "Item: <a short, clear name for the item>\n"
        "Category: <the single matching category id from the list above, exactly as written>"
    )


def _parse_classification_response(raw_text: str, categories: list[dict]) -> tuple[str, Optional[dict]]:
    """
    Parses the model's two-line answer.

    Returns (item_name, None) if the model flagged the input as off_topic,
    meaning it does not describe a waste item at all. Falls back to
    mixed_waste if the category id isn't recognized as one of the known ids
    (a malformed or unexpected reply is not the same thing as a deliberate
    off-topic flag, so it still gets a safe category rather than being
    silently treated as off-topic).
    """
    item_name = "the item"
    category_id = "mixed_waste"

    for line in raw_text.strip().splitlines():
        line = line.strip()
        if line.lower().startswith("item:"):
            item_name = line.split(":", 1)[1].strip()
        elif line.lower().startswith("category:"):
            category_id = line.split(":", 1)[1].strip().lower()

    if category_id == "off_topic":
        return item_name, None

    valid_ids = {cat["id"] for cat in categories}
    if category_id not in valid_ids:
        category_id = "mixed_waste"

    matched_category = next(cat for cat in categories if cat["id"] == category_id)
    return item_name, matched_category


class AIService:
    """
    Application service layer responsible for validating user input,
    orchestrating model client requests, and catching exceptions gracefully.
    """

    def __init__(self, model_client: Optional[OllamaModelClient] = None):
        # Allow injecting custom/mock model_client for simple testing
        self.model_client = model_client

    def _get_client(self) -> OllamaModelClient:
        """Returns active model client, initializing default client if none provided."""
        if self.model_client is None:
            self.model_client = OllamaModelClient()
        return self.model_client

    def process_message(self, user_message: str) -> AIResponse:
        """
        Processes a raw user message string and returns a structured AIResponse.
        Catches technical failures and converts them to friendly user-facing messages.
        """
        # 1. Validate empty input
        if not user_message or not user_message.strip():
            return AIResponse(
                content="Please enter a message before sending.",
                success=False,
                error_message="User message was empty.",
            )

        try:
            # 2. Schema validation
            request = UserRequest(message=user_message.strip())

            # 3. Call model client
            client = self._get_client()
            response_text = client.generate(request.message)

            return AIResponse(
                content=response_text,
                success=True,
            )

        except OllamaConnectionError as err:
            return AIResponse(
                content=(
                    "[Error] Could not connect to Ollama.\n\n"
                    "Please verify that Ollama is installed and running locally on your machine."
                ),
                success=False,
                error_message=str(err),
            )

        except ModelNotFoundError as err:
            return AIResponse(
                content=(
                    f"[Error] The configured AI model is unavailable in Ollama.\n\n"
                    f"Please verify your MODEL_NAME setting or run 'ollama run <model_name>'."
                ),
                success=False,
                error_message=str(err),
            )

        except ModelClientError as err:
            return AIResponse(
                content="[Error] An unexpected communication error occurred with the AI model.",
                success=False,
                error_message=str(err),
            )

        except Exception as err:
            return AIResponse(
                content="[Error] An unexpected application error occurred.",
                success=False,
                error_message=str(err),
            )

    def process_recycling_query(self, user_message: str) -> RecyclingResponse:
        """
        Classifies a described item using the model, then looks up the real
        disposal facts from data/finland_waste_categories.json — the model
        never generates disposal facts itself, only picks a category label
        (or flags the input as off_topic).

        Raises OutOfScopeInput if the model determines the input does not
        describe a waste item at all, rather than forcing it into a
        nonsensical category.
        """
        categories = _load_waste_categories()
        client = self._get_client()

        prompt = _build_classification_prompt(user_message.strip(), categories)
        raw_response = client.generate(prompt)

        item_name, matched_category = _parse_classification_response(raw_response, categories)

        if matched_category is None:
            raise OutOfScopeInput(user_message.strip())

        return RecyclingResponse(
            identified_item=item_name,
            disposal_category=matched_category["name"],
            recycled_into=matched_category.get("recycled_into"),
        )

    def process_recycling_image(self, image_bytes: bytes) -> RecyclingResponse:
        """
        Identifies a waste item from a photo using the vision model, then reuses
        the same text-based classification logic and reference dataset lookup as
        the text path. The vision model's only job is to name the item — moondream
        struggles to both identify an item AND pick from a long category list in a
        single call, so classification (including the off_topic check) is handled
        identically regardless of whether the input was typed text or a photo.
        """
        client = self._get_client()

        description_prompt = (
            "What is the main object in this image? Answer with just a short phrase "
            "naming the item and its likely material (for example: 'cardboard pizza box', "
            "'glass bottle', 'plastic bag'). Ignore any text, logos, or branding printed on "
            "the item — describe the physical object itself, not what it says."
        )
        item_description = client.generate_vision(description_prompt, image_bytes).strip()

        return self.process_recycling_query(item_description)


def generate_response(user_message: str, service: Optional[AIService] = None) -> str:
    """
    Main reusable service entry point used by the UI layer.

    Accepts user input message, passes it to the AI service, and returns
    the generated text response (or a friendly error message).
    """
    active_service = service or AIService()
    response = active_service.process_message(user_message)
    return response.content


def _record_history_safely(result: RecyclingResponse) -> None:
    """
    Appends a successful classification to the local history file. Wrapped so
    that a history-write failure (e.g. a read-only filesystem) never breaks
    the user-facing response, since remembering past items is a convenience,
    not a requirement for answering the current one.
    """
    try:
        record_entry(result.identified_item, result.disposal_category, result.recycled_into)
    except OSError:
        pass


def _format_recycling_response(result: RecyclingResponse) -> str:
    lines = [f"**Item:** {result.identified_item}", f"**Disposal category:** {result.disposal_category}"]
    if result.recycled_into:
        lines.append(f"**Recycled into:** {result.recycled_into}")
    return "\n\n".join(lines)


def generate_recycling_response(user_message: str, service: Optional[AIService] = None) -> str:
    """
    Entry point the UI will call for recycling queries. Returns a friendly,
    formatted answer, a polite redirect for off-topic input, or a friendly
    error message if something goes wrong.
    """
    if not user_message or not user_message.strip():
        return "Please describe the item (e.g. 'pizza box') before sending."

    active_service = service or AIService()

    try:
        result = active_service.process_recycling_query(user_message)
        _record_history_safely(result)
        return _format_recycling_response(result)

    except OutOfScopeInput:
        return (
            "That doesn't look like a waste item to sort. WasteBuddy can only help with "
            "figuring out how to dispose of things, so try describing an item (for example "
            "'yogurt tub' or 'old phone charger'), or upload a photo of it instead."
        )
    except OllamaConnectionError:
        return "[Error] Could not connect to Ollama. Please verify that Ollama is installed and running locally."
    except ModelNotFoundError:
        return "[Error] The configured AI model is unavailable in Ollama. Check your MODEL_NAME setting."
    except ModelClientError:
        return "[Error] An unexpected communication error occurred with the AI model."
    except Exception:
        return "[Error] An unexpected application error occurred."


def generate_recycling_response_from_image(image_bytes: bytes, service: Optional[AIService] = None) -> str:
    """
    Entry point the UI will call for image-based recycling queries. Returns a
    friendly, formatted answer, a polite redirect if the photo doesn't show a
    waste item, or a friendly error message if something goes wrong.
    """
    if not image_bytes:
        return "Please upload a photo before sending."

    active_service = service or AIService()

    try:
        result = active_service.process_recycling_image(image_bytes)
        _record_history_safely(result)
        return _format_recycling_response(result)

    except OutOfScopeInput:
        return (
            "That doesn't look like a photo of a waste item to sort. WasteBuddy can only help "
            "with figuring out how to dispose of things, so try a clearer photo of the item, or "
            "describe it in words instead."
        )
    except OllamaConnectionError:
        return "[Error] Could not connect to Ollama. Please verify that Ollama is installed and running locally."
    except ModelNotFoundError:
        return "[Error] The configured vision model is unavailable in Ollama. Check your VISION_MODEL_NAME setting."
    except ModelClientError:
        return "[Error] An unexpected communication error occurred with the AI model."
    except Exception:
        return "[Error] An unexpected application error occurred."
