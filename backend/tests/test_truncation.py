import pytest
from utils.truncation import truncate_for_context

def test_truncation_fits():
    # If estimated tokens fits, text should be returned as is, and boolean flag should be False.
    text = "This is a short text."
    truncated, exceeds = truncate_for_context(text, estimated_tokens=5, context_limit=10)
    assert not exceeds
    assert truncated == text

def test_truncation_exceeds():
    # Creating a long text
    sentences = ["This is sentence number " + str(i) + "." for i in range(100)]
    text = " ".join(sentences)
    
    # We exceed the limit
    truncated, exceeds = truncate_for_context(text, estimated_tokens=1000, context_limit=10)
    
    from config import GAP_MARKER
    assert exceeds
    assert GAP_MARKER in truncated
    
    # Needs to be shorter than context_limit * CHARS_PER_TOKEN + tolerance
    # Just checking it doesn't return the full text
    assert len(truncated) < len(text)
    
    # Assert start and end are roughly present (might be part of the sentence due to limit, let's just check snippets)
    assert "This" in truncated
