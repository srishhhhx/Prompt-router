import pytest
from utils.pii import scrub_document, sync_prompt_with_tokens, rehydrate, StreamRehydrator
from session import SESSIONS

def test_scrub_document():
    text = "My PAN is ABCDE1234F and IFSC is ABCD0123456."
    res = scrub_document(text)
    
    scrubbed = res["scrubbed_text"]
    tokens = res["token_map"]
    
    assert "ABCDE1234F" not in scrubbed
    assert "ABCD0123456" not in scrubbed
    
    # Expected output should have {{PAN_1}} and {{IFSC_1}}
    assert "{{PAN_1}}" in scrubbed
    assert "{{IFSC_1}}" in scrubbed
    assert len(tokens) == 2
    assert tokens["{{PAN_1}}"] == "ABCDE1234F"
    assert tokens["{{IFSC_1}}"] == "ABCD0123456"

def test_sync_prompt_with_tokens():
    SESSIONS["test_session"] = {
        "token_map": {"{{PAN_1}}": "ABCDE1234F"}
    }
    
    prompt = "What is the balance for PAN ABCDE1234F and PAN XYZDE1234G?"
    synced = sync_prompt_with_tokens(prompt, "test_session")
    
    assert "{{PAN_1}}" in synced
    assert "ABCDE1234F" not in synced
    # Since XYZDE1234G is not in the token map, it should be scrubbed with UNKNOWN
    assert "{{UNKNOWN_PAN_1}}" in synced
    assert "XYZDE1234G" not in synced

def test_rehydrate():
    SESSIONS["test_session_2"] = {
        "token_map": {"{{PAN_1}}": "ABCDE1234F"}
    }
    
    text = "The PAN number found is {{PAN_1}}."
    restored = rehydrate(text, "test_session_2")
    
    assert "ABCDE1234F" in restored
    assert "{{PAN_1}}" not in restored

def test_stream_rehydrator():
    SESSIONS["test_session_3"] = {
        "token_map": {"{{PAN_1}}": "ABCDE1234F"}
    }
    rehydrator = StreamRehydrator("test_session_3")
    
    out1 = rehydrator.process("Hello, your PAN is {{P")
    out2 = rehydrator.process("AN_1}} and it is valid.")
    
    assert out1 == "Hello, your PAN is "
    assert out2 == "ABCDE1234F and it is valid."
