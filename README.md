# Norwegian DOCX Translator

A Dockerized Streamlit app that translates Norwegian `.docx` files to English, with full formatting preservation. Served on LAN from WSL2.

## How it works

1. Upload one or more `.docx` files and select source language (Bokmål, Nynorsk, or auto-detect)
2. The document is sent to the **Azure Synchronous Document Translation API** — translated DOCX is returned with formatting intact
3. In parallel, **Claude claude-sonnet-4-6** (via Azure AI Foundry) produces a plain-text translation as a fallback
4. Both files are written to disk and served as direct download links (no RAM buffering)
5. Multi-file uploads produce a ZIP containing all `.docx` and `.txt` outputs

The `.txt` fallback is useful when Azure skips proper nouns or brand names (a known Azure behaviour).

Translated files are cached on disk for 24 hours by SHA-256 key — re-uploading the same file skips all API calls.

## Setup

### Requirements

- Docker + Docker Compose
- Azure Cognitive Services Translator resource (S1, custom domain, synchronous document translation API)
- Azure AI Foundry deployment of `claude-sonnet-4-6`

### Configuration

```bash
cp .env.example .env
# Fill in values — see table below
```

| Variable | Description |
|---|---|
| `AZURE_TRANSLATOR_ENDPOINT` | `https://<your-resource>.cognitiveservices.azure.com/` |
| `AZURE_TRANSLATOR_KEY` | Cognitive Services key |
| `ANTHROPIC_API_KEY` | Azure AI Foundry API key |
| `ANTHROPIC_BASE_URL` | Azure AI Foundry Anthropic endpoint |

### Run with Docker

```bash
docker compose up --build -d   # build and start
docker logs translator_app     # stdout logs
tail -f logs/translator.log    # rolling file log (max 10 000 lines)
docker compose down            # stop
```

App is available at `http://localhost:8502`.

### Run locally (without Docker)

```bash
uv sync
uv run streamlit run app.py --server.enableStaticServing=true
```

## File structure

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI — upload, language selector, download links |
| `translator.py` | Translation pipeline — Azure Document Translation + Claude |
| `credits_logger.py` | Rolling log handler (keeps last N lines) |
| `Dockerfile` | uv + Python 3.14, port 8502, static file serving enabled |
| `docker-compose.yml` | Port mapping, env file, volume mounts for logs and cache |
| `.env.example` | Template for required environment variables |
