"""
schemas/extraction.py — FinancialStatementSchema: output of the Extractor module.

Most fields are Optional because the document may be an invoice (no revenue)
or a bank statement (no net_profit). key_line_items captures domain-specific
rows that don't fit the standard fields.

Phase B note: schema selection (invoice vs balance_sheet vs annual_report)
based on ClassificationResult.document_type is a Phase B addition.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class FinancialStatementSchema(BaseModel):
    document_type: str = Field(
        description="Detected document type (e.g. 'annual_report', 'invoice')."
    )
    date_range: Optional[str] = Field(
        default=None,
        description="Period covered by the document (e.g. 'FY 2023-24')."
    )
    revenue: Optional[str] = Field(
        default=None,
        description="Total revenue or turnover as a string with units."
    )
    net_profit: Optional[str] = Field(
        default=None,
        description="Net profit or loss as a string with units."
    )
    total_assets: Optional[str] = Field(
        default=None,
        description="Total assets as a string with units."
    )
    total_liabilities: Optional[str] = Field(
        default=None,
        description="Total liabilities as a string with units."
    )
    key_line_items: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Additional key figures not captured by the standard fields. "
                    "Each item is a dict with 'label' and 'value' keys."
    )
    flagged_anomalies: List[str] = Field(
        default_factory=list,
        description="Notable anomalies or concerns found in the document."
    )
    extraction_confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence that the extracted values are accurate."
    )
