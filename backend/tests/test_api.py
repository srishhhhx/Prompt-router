import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_session_creation():
    response = client.post("/session")
    assert response.status_code == 201
    
    data = response.json()
    assert "session_id" in data
    assert data["status"] == "ready"

def test_status_endpoint_not_found():
    response = client.get("/status/non_existent_session")
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found or expired."
