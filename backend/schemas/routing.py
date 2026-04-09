"""
schemas/routing.py — RoutingDecision: output of the Intent Router.
"""

from pydantic import BaseModel, Field
from typing import Literal


class RoutingDecision(BaseModel):
    intent: Literal["extraction", "summarization", "classification"] = Field(
        description="The processing module to route this request to."
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in the routing decision, 0–1."
    )
    reasoning: str = Field(
        description="One sentence explaining why this intent was chosen."
    )
