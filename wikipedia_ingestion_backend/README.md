# Wikipedia Ingestion Backend (Django)

Django backend for uploading CSVs of Wikipedia topics/links, processing content via a RAG pipeline (LangChain + chunking + embeddings), and ingesting results into a Neo4j knowledge graph.

- Swagger UI: /docs
- ReDoc: /redoc
- Raw schema: /swagger.json

Generate OpenAPI schema file:
- From project root (this folder): `python manage.py generate_openapi --host localhost:8000 --scheme http --base-path /api`
- Output: `wikipedia_ingestion_backend/interfaces/openapi.json`

## Overview

- Ingestion flow: CSV or single value → Wikipedia fetch → LangChain chunking → embeddings (local sentence-transformers by default, optional OpenAI) → Neo4j write.
- Django uses SQLite for application metadata; Neo4j stores the knowledge graph.
- Background execution via a thread pool (ThreadPoolExecutor) is enabled by default. You can disable it for deterministic behavior with USE_SYNC_INGEST.

## Quickstart

1) Create a virtual environment and install dependencies
- Run these in the Django project root (this directory contains manage.py):
```
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```
If you plan to use OpenAI embeddings, also install the OpenAI client:
```
pip install openai
```

2) Configure environment variables (.env)
- Create a `.env` file next to manage.py. Example:
```
# Django
DJANGO_SECRET_KEY=unsafe-dev-key-change-me
DEBUG=true
ALLOWED_HOSTS=localhost,127.0.0.1

# Neo4j connectivity (required for ingestion to Neo4j)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=yourpassword

# Embeddings provider
# Default is local sentence-transformers (no API key needed)
EMBEDDINGS_PROVIDER=sentence-transformers
# Optional: only when EMBEDDINGS_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDINGS_MODEL=text-embedding-3-small

# Chunking and timeouts
RAG_CHUNK_SIZE=1000
RAG_CHUNK_OVERLAP=150
REQUEST_TIMEOUT=60

# Background execution
MAX_WORKERS=4
# If "true"/"1", disable background threads and run ingestion in the request thread
USE_SYNC_INGEST=

# Optional docs generation hints for openapi export
SITE_HOST=localhost:8000
SITE_SCHEME=http
```

3) Apply migrations
```
python manage.py migrate
```

4) Run the development server
```
python manage.py runserver 0.0.0.0:8000
```
- Health: http://localhost:8000/api/health/
- Docs:
  - Swagger UI: http://localhost:8000/docs
  - ReDoc: http://localhost:8000/redoc
  - Raw schema: http://localhost:8000/swagger.json

## Environment Variables

Django/platform
- DJANGO_SECRET_KEY: Required in production. A default is used for dev.
- DEBUG: true/false; do not enable in production.
- ALLOWED_HOSTS: Comma-separated allowlist (include your host when DEBUG=false).

Neo4j (required for actual ingestion to the graph)
- NEO4J_URI: e.g., bolt://localhost:7687 or neo4j+s://host
- NEO4J_USER
- NEO4J_PASSWORD

Embeddings
- EMBEDDINGS_PROVIDER: "sentence-transformers" (default) or "openai"
- OPENAI_API_KEY: Only required when EMBEDDINGS_PROVIDER=openai
- OPENAI_EMBEDDINGS_MODEL: Optional override (default text-embedding-3-small)

Chunking and timeouts
- RAG_CHUNK_SIZE: Default 1000
- RAG_CHUNK_OVERLAP: Default 150
- REQUEST_TIMEOUT: Default 60 seconds for HTTP and Wikipedia client calls

Background execution
- MAX_WORKERS: Thread pool size (default 4)
- USE_SYNC_INGEST: If set to a truthy value ("true"/"1"/"yes"/"on"), disable background execution and run ingestion synchronously in the request thread (useful for deterministic tests or constrained environments)

Docs/OpenAPI export
- SITE_HOST: Hostname used when exporting OpenAPI (e.g., localhost:8000)
- SITE_SCHEME: http or https

Notes:
- OpenAI is optional. It is only needed if EMBEDDINGS_PROVIDER=openai. If you never turn that on, you do not need the OPENAI_API_KEY nor the openai package installed.
- The app reads `.env` automatically using django-environ.

## Running Locally

- Start Neo4j and ensure the environment variables point to it.
- Start Django with `python manage.py runserver 0.0.0.0:8000`.
- Visit /docs to explore and try endpoints.

## API Endpoints (Base path /api)

- GET /api/health/
- POST /api/ingest/upload-csv/ (multipart/form-data; field name: csv_file; optional column_name, has_header, config)
- POST /api/ingest/single/ (JSON: {"value": "<topic or URL>", "source_type": "TOPIC|LINK" (optional), "config": {...} (optional)})
- GET /api/ingest/jobs/{job_id}/
- GET /api/ingest/jobs/{job_id}/items/

Standard response envelope across endpoints:
- success: boolean
- job_id: integer (when applicable)
- status: current job status
- counts: total, processed, succeeded, failed (when applicable)
- error/detail: context-specific information

## Testing

The project includes comprehensive unit and API tests in api/tests.py.

Recommended deterministic test settings:
- Set USE_SYNC_INGEST=true to force synchronous pipeline execution so tests do not rely on background threads:
  - In CI or terminal before running tests:
    ```
    export USE_SYNC_INGEST=true
    ```
  - tests.py already sets USE_SYNC_INGEST=true at import time to ensure determinism.

Run tests:
```
python manage.py test
```

Mocked external services in tests:
- Wikipedia fetching is mocked at the service layer (api.services.wikipedia_client.*) to avoid network calls.
- Chunking uses a mocked LangChain splitter where appropriate.
- Embeddings:
  - Default path (sentence-transformers) is mocked so no model download occurs.
  - OpenAI path is also mocked; no real API calls are made. OPENAI_API_KEY is only used when specifically testing the OpenAI path.
- Neo4j driver/session is mocked for unit tests that exercise write logic; a separate optional smoke test checks only for env presence.

Optional smoke test around Neo4j:
- Will only run if NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD are present. It does not actually connect, it just verifies env presence.

## OpenAPI Export

Generate a static OpenAPI schema JSON that embeds the correct scheme/host/base-path:
```
python manage.py generate_openapi --host localhost:8000 --scheme http --base-path /api
```
Output is written to:
- `interfaces/openapi.json`

In addition, live documentation is served at:
- /docs (Swagger UI)
- /redoc (ReDoc)
- /swagger.json (raw)

## Troubleshooting

Neo4j connectivity/auth
- Ensure NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD are set correctly.
- For secure connections (neo4j+s://), ensure certificates/network are properly configured.
- Verify the instance is reachable from the host running Django.

Wikipedia fetch timeouts or slow pages
- Increase REQUEST_TIMEOUT in your environment if you see timeouts regularly.
- Retries are built-in for resilience.

Embeddings/model behavior
- Default sentence-transformers runs locally; first run may download a model (ensure internet access).
- For OpenAI embeddings, EMBEDDINGS_PROVIDER must be "openai" and OPENAI_API_KEY must be set; also ensure `pip install openai`.
- If embeddings fail at runtime, the pipeline logs the error and continues (ingestion proceeds without storing embeddings).

Background execution
- Tune MAX_WORKERS to manage concurrency.
- If you run in an environment that restricts threads or you want deterministic runs (e.g., CI), set USE_SYNC_INGEST=true.

ALLOWED_HOSTS when deploying
- Include your host/domain/IP in ALLOWED_HOSTS when DEBUG=false or you will receive 400 responses.

## Project Layout

- config/: Django settings and URL routing
- api/: Models, views, serializers, services (csv parsing, wikipedia client, chunking, embeddings, neo4j writer), background task helpers, tests
- interfaces/: Generated OpenAPI specs
- manage.py: Django management entrypoint
