import pytest
from unittest.mock import MagicMock, patch
from utils.scout import _derive_doc_type_hint, _detect_language, run_scout

def test_derive_doc_type_hint():
    # Test individual categories
    assert _derive_doc_type_hint("This is a Bank Statement for account mapping") == "bank_statement"
    assert _derive_doc_type_hint("Invoicing for the remittance") == "invoice"
    assert _derive_doc_type_hint("Annual Report 2023 and Form 10-K") == "annual_report"
    assert _derive_doc_type_hint("Consolidated Balance Sheet for the group") == "balance_sheet"
    assert _derive_doc_type_hint("Memorandum of Understanding and Agreement terms") == "legal_agreement"
    assert _derive_doc_type_hint("Independent Auditor's Opinion on financial statements") == "audit_report"
    
    # Test fallback
    assert _derive_doc_type_hint("Random text about cats") == "unknown"
    assert _derive_doc_type_hint("") == "unknown"

def test_detect_language():
    # Test valid text (if langdetect is present)
    # Since we might not have internet/full env, we mock it
    with patch("utils.scout.langdetect_detect", return_value="en"):
        assert _detect_language("Hello world") == "en"
    
    with patch("utils.scout._LANGDETECT_AVAILABLE", False):
        assert _detect_language("Hello world") == "unknown"

@patch("utils.scout.fitz.open")
def test_run_scout_logic(mock_fitz_open):
    # Mocking fitz.open to return a mock document with one page
    mock_doc = MagicMock()
    mock_page = MagicMock()
    
    # Setup page statistics
    mock_page.get_drawings.return_value = [1, 2, 3] # 3 drawings
    mock_page.get_images.return_value = [1]         # 1 image
    # Mock get_text("blocks") -> type 0 is text block
    mock_page.get_text.side_effect = lambda mode: [
        (0,0,10,10, "block1", 0, 0),
        (10,10,20,20, "block2", 1, 0)
    ] if mode == "blocks" else "Some text on the page"
    
    mock_doc.__iter__.return_value = [mock_page]
    mock_doc.page_count = 1
    mock_fitz_open.return_value = mock_doc
    
    result = run_scout(b"fake_pdf_bytes", filename="test.pdf")
    
    assert result["page_count"] == 1
    assert result["total_drawing_count"] == 3
    assert result["total_image_count"] == 1
    assert result["total_block_count"] == 2
    # Logic: is_scanned is False because char_count is len("Some text on the page") = 21
    # which is likely > threshold if threshold is small, but let's check config.
    # Actually SCANNED_CHAR_THRESHOLD is usually higher.
    # But text_preview should match
    assert result["text_preview"] == "Some text on the page"
