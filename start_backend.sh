#!/usr/bin/env bash
# start_backend.sh
# Runs the FastAPI backend server and suppresses the LibreSSL urllib3 warning on macOS

# Navigate to the backend directory relative to where the script is located
cd "$(dirname "$0")/backend" || exit 1

echo "[*] Activating virtual environment..."
source venv/bin/activate

# Ignore the urllib3 LibreSSL warning (safe to ignore on macOS)
export PYTHONWARNINGS="ignore:::urllib3"

# Include backend directory in Python path
export PYTHONPATH="."

echo "[*] Starting FastAPI server on http://127.0.0.1:8000..."
echo "[*] Press CTRL+C to quit"
echo ""

# Start Uvicorn
uvicorn main:app --port 8000
