import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from utils.parser_factory import parse_document
from config import PARSER_SIMPLE, PARSER_LLAMAPARSE, PARSER_DOCLING, PARSER_FALLBACK

@pytest.mark.asyncio
@patch("utils.parser_factory._extract_pymupdf")
async def test_parse_document_simple_path(mock_extract_pymupdf):
    mock_extract_pymupdf.return_value = "Simple text"
    scout_result = {
        "is_scanned": False,
        "has_complex_layout": False,
        "likely_has_tables": False
    }
    
    result = await parse_document(b"fake", scout_result, "test.pdf")
    
    assert result["parser_used"] == PARSER_SIMPLE
    assert result["parsed_text"] == "Simple text"
    mock_extract_pymupdf.assert_called_once()

@pytest.mark.asyncio
@patch("utils.parser_factory._try_llamaparse", new_callable=AsyncMock)
async def test_parse_document_llamaparse_success(mock_llamaparse):
    mock_llamaparse.return_value = "Markdown from LlamaParse"
    scout_result = {
        "is_scanned": True,
        "has_complex_layout": False,
        "likely_has_tables": False
    }
    
    result = await parse_document(b"fake", scout_result, "test.pdf")
    
    assert result["parser_used"] == PARSER_LLAMAPARSE
    assert result["parsed_text"] == "Markdown from LlamaParse"
    mock_llamaparse.assert_called_once()

@pytest.mark.asyncio
@patch("utils.parser_factory._try_llamaparse", new_callable=AsyncMock)
@patch("utils.parser_factory._try_docling", new_callable=AsyncMock)
async def test_parse_document_cascade_to_docling(mock_docling, mock_llamaparse):
    mock_llamaparse.return_value = None
    mock_docling.return_value = "Markdown from Docling"
    scout_result = {
        "is_scanned": False,
        "has_complex_layout": True,
        "likely_has_tables": False
    }
    
    result = await parse_document(b"fake", scout_result, "test.pdf")
    
    assert result["parser_used"] == PARSER_DOCLING
    assert result["parsed_text"] == "Markdown from Docling"
    mock_llamaparse.assert_called_once()
    mock_docling.assert_called_once()

@pytest.mark.asyncio
@patch("utils.parser_factory._try_llamaparse", new_callable=AsyncMock)
@patch("utils.parser_factory._try_docling", new_callable=AsyncMock)
@patch("utils.parser_factory._extract_pymupdf")
async def test_parse_document_fallback_to_pymupdf(mock_extract, mock_docling, mock_llamaparse):
    mock_llamaparse.return_value = None
    mock_docling.return_value = None
    mock_extract.return_value = "Degraded text"
    scout_result = {
        "is_scanned": False,
        "has_complex_layout": False,
        "likely_has_tables": True
    }
    
    result = await parse_document(b"fake", scout_result, "test.pdf")
    
    assert result["parser_used"] == PARSER_FALLBACK
    assert result["parsing_quality"] == "degraded"
    assert result["parsed_text"] == "Degraded text"
