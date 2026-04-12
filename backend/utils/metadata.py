"""
metadata.py — Metadata packet assembly.

Assembles routing and processing fields from scout outputs and parser results.
"""


def assemble_metadata(scout_result: dict, parser_result: dict) -> dict:
    """Build the metadata packet from scout and parser outputs."""
    return {
        # Router Fields
        "page_count":          scout_result["page_count"],
        "likely_has_tables":   scout_result["likely_has_tables"],
        "text_preview":        scout_result["text_preview"],
        "doc_type_hint":       scout_result["doc_type_hint"],
        
        # Summarizer / Extractor / Classifier Fields
        "estimated_tokens":    scout_result.get("estimated_tokens", 0),
        
        # Parser Factory & UX Flags
        "is_scanned":          scout_result["is_scanned"],
        "has_complex_layout":  scout_result["has_complex_layout"],
        "language":            scout_result["language"],
        "parsing_quality":     parser_result["parsing_quality"],
        "parser_used":         parser_result["parser_used"],
        
        # Logged Telemetry (Observability)
        "total_char_count":    scout_result["total_char_count"],
        "avg_chars_per_block": scout_result["avg_chars_per_block"],
        "total_block_count":   scout_result["total_block_count"],
        "total_drawing_count": scout_result["total_drawing_count"],
        "total_image_count":   scout_result["total_image_count"],
        "per_page_char_count": scout_result.get("per_page_char_count", []),
    }
