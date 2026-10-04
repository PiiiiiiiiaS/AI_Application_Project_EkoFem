from pydantic import BaseModel, Field

class UserRequest(BaseModel):
    """Minimal schema for validating incoming user input."""

    message: str = Field(..., description="The user's prompt or message.")

class AIResponse(BaseModel):
    """Minimal schema for structured response output from the AI service layer."""

    content: str = Field(..., description="The generated response text or user-friendly error message.")
    success: bool = Field(True, description="Flag indicating if the operation succeeded.")
    error_message: str | None = Field(None, description="Detailed error description if success is False.")

class RecyclingResponse(BaseModel):
    """Structured result for a recycling query — one item identified, mapped to Finland's official waste categories."""

    identified_item: str = Field(..., description="The waste item identified from the user's text description or uploaded photo.")
    disposal_category: str = Field(..., description="The correct disposal category for this item, looked up from data/finland_waste_categories.json rather than the model's own guess.")
    recycled_into: str | None = Field(None, description="What this material typically becomes after being recycled — its real downstream destination (e.g. 'new glass bottles'), looked up from the reference dataset rather than a personal reuse idea.")