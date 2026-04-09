"""
schemas/classification.py — ClassificationResult: output of the Classifier module.
"""

from pydantic import BaseModel, Field
from typing import Literal, List


class ClassificationResult(BaseModel):
    document_type: Literal[
        "annual_report",
        "audit_report",
        "balance_sheet",
        "invoice",
        "bank_statement",
        "legal_agreement",
        "other",
    ] = Field(description="The detected financial document category.")
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence.")
    key_signals: List[str] = Field(
        description="Short phrases or features that led to this classification."
    )
