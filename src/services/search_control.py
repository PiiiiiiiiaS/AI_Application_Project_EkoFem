"""
Lets the UI stop a running search.

The local model cannot be interrupted in the middle of a reply, so "stop" works
like this: the UI stops waiting at once and discards the answer, and this
module makes sure an abandoned search never writes anything to the history
file when the model finally finishes in the background.

It adds to the AI service without changing it: CancellableAIService is a thin
subclass of AIService that checks a CancelToken before and after the model call.
It also remembers the id of the waste category the item was sorted into, so the
UI can offer the matching drop-off section without asking the user again.
"""
import threading
from typing import Optional

from src.models.model_client import OllamaModelClient
from src.services.ai_service import AIService, _load_waste_categories


class SearchCancelled(Exception):
    """Raised inside a search that the user has stopped."""


class CancelToken:
    """A flag the UI sets when the user presses "Stop search"."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


def _category_id_for(category_name: str) -> Optional[str]:
    """Finds the id (e.g. 'hazardous_waste') of a category from its display name."""
    for category in _load_waste_categories():
        if category["name"] == category_name:
            return category["id"]
    return None


class CancellableAIService(AIService):
    """AIService that gives up (and so records nothing) once its token is cancelled."""

    def __init__(self, token: CancelToken, model_client: Optional[OllamaModelClient] = None):
        super().__init__(model_client=model_client)
        self.token = token
        self.category_id: Optional[str] = None  # set after a successful classification

    def process_recycling_query(self, user_message: str):
        if self.token.cancelled:
            raise SearchCancelled()
        result = super().process_recycling_query(user_message)
        if self.token.cancelled:
            raise SearchCancelled()
        self.category_id = _category_id_for(result.disposal_category)
        return result

    def process_recycling_image(self, image_bytes: bytes):
        if self.token.cancelled:
            raise SearchCancelled()
        return super().process_recycling_image(image_bytes)
