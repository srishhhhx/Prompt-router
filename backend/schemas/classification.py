"""
schemas/classification.py — ClassificationResult: output of the Classifier module.

Document taxonomy aligned to the six sample document categories provided:
  1. financial_statements   — Full set (Balance Sheet + P&L + Capital Account) for a proprietor/individual
  2. balance_sheet          — Standalone statement of financial position
  3. profit_loss            — Standalone Profit & Loss / Income Statement
  4. cash_flow_statement    — Standalone Cash Flow Statement (operating/investing/financing)
  5. annual_report          — Corporate annual report with multiple financial statements + disclosures
  6. audit_report           — Independent Auditor's Report / Audit findings
  7. commercial_invoice     — Commercial/export invoice with line items, pricing, trade details
  8. bank_statement         — Bank account transaction history (NEFT, deposits, withdrawals, balances)
  9. legal_agreement        — Contract, MOU, or legal document with financial terms
  10. other                 — Any financial document not matching the above categories
"""

from pydantic import BaseModel, Field
from typing import Literal, List


class ClassificationResult(BaseModel):
    document_type: Literal[
        "financial_statements",
        "balance_sheet",
        "profit_loss",
        "cash_flow_statement",
        "annual_report",
        "audit_report",
        "commercial_invoice",
        "bank_statement",
        "legal_agreement",
        "other",
    ] = Field(description="The detected financial document category.")
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence.")
    key_signals: List[str] = Field(
        description="3–5 short phrases or features that led to this classification."
    )
