"""
metadata.py — MVP metadata packet assembly.

Assembles the six fields that directly influence routing and processing decisions
from scout outputs and parser results. All additional metadata is a Phase B addition.
"""


def assemble_metadata(scout_result: dict, parser_result: dict) -> dict:
    """
    Build the MVP metadata packet from scout and parser outputs.

    MVP packet — 6 fields:
        page_count        — drives strategy selection in the router
        likely_has_tables — influences processing approach for extraction
        is_scanned        — informs the user about document quality
        language          — flags non-English documents
        parser_used       — records which parser ran
        text_preview      — first N chars for LLM domain awareness in the router
        parsing_quality   — "normal" | "degraded"

    Returns a flat dict safe to store in SESSIONS and serialise to JSON.
    """
    return {
        "page_count":        scout_result["page_count"],
        "likely_has_tables": scout_result["likely_has_tables"],
        "is_scanned":        scout_result["is_scanned"],
        "language":          scout_result["language"],
        "parser_used":       parser_result["parser_used"],
        "text_preview":      scout_result["text_preview"],
        "parsing_quality":   parser_result["parsing_quality"],
    }
