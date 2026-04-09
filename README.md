# FDIP — Financial Document Intelligence Pipeline

A production-aware document intelligence system that accepts user prompts and documents, identifies intent, and routes to the appropriate processing module.

## Quick Start

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in API keys
uvicorn main:app --reload
```

## Architecture

See `Master-doc.md` for the full design document and architecture.

## License

Apache 2.0
