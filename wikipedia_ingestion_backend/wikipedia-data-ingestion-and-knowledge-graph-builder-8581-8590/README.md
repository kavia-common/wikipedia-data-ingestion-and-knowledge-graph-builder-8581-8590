# Wikipedia Data Ingestion and Knowledge Graph Builder (Django Backend)

This backend reads Wikipedia topics or links (via CSV upload or single input), retrieves content, chunks and embeds it through a RAG pipeline, and ingests the results into a Neo4j knowledge graph.

API documentation:
- Swagger UI: /docs
- ReDoc: /redoc
- Raw schema: /swagger.json

Generate OpenAPI schema file:
- From project root: `python manage.py generate_openapi --host localhost:8000 --scheme http --base-path /api`
- Output: `wikipedia_ingestion_backend/interfaces/openapi.json`

## Overview

- Ingestion flow: CSV or single value → Wikipedia fetch → chunking (LangChain) → embeddings (local sentence-transformers or optional OpenAI) → Neo4j write.
- Django uses SQLite for app metadata; Neo4j stores the knowledge graph.
- Background execution via a thread pool is enabled by default and can be disabled with USE_SYNC_INGEST for constrained environments.

## Prerequisites

- Python 3.10+
- Neo4j instance reachable from the app
- Optional: OpenAI API key if using OpenAI embeddings

## Setup

### 1) Create a virtual environment and install dependencies
- Navigate to the Django project root (contains manage.py): `wikipedia-data-ingestion-and-knowledge-graph-builder-8581-8590/wikipedia_ingestion_backend`
- Then:

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

### 2) Configure environment variables (.env)

Create a `.env` file in the Django project root (same folder as manage.py). Example:

```
# Django
DJANGO_SECRET_KEY=unsafe-dev-key-change-me
DEBUG=true
ALLOWED_HOSTS=localhost,127.0.0.1

# Neo4j connectivity
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=yourpassword

# Embeddings provider
# Default is local sentence-transformers (no network); for OpenAI set EMBEDDINGS_PROVIDER=openai
EMBEDDINGS_PROVIDER=sentence-transformers
# Optional: when using OpenAI
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDINGS_MODEL=text-embedding-3-small

# Chunking and timeouts
RAG_CHUNK_SIZE=1000
RAG_CHUNK_OVERLAP=150
REQUEST_TIMEOUT=60

# Background execution
MAX_WORKERS=4
# If true/1, disable threads and run ingestion in the request thread
USE_SYNC_INGEST=

# Optional docs generation hints
SITE_HOST=localhost:8000
SITE_SCHEME=http
```

Environment variables used by the app:
- NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD (required for ingestion)
- EMBEDDINGS_PROVIDER (default: sentence-transformers)
- Optional for OpenAI: OPENAI_API_KEY, OPENAI_EMBEDDINGS_MODEL
- RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP (chunking behavior)
- REQUEST_TIMEOUT (Wikipedia and HTTP fetch timeouts)
- MAX_WORKERS (thread pool size)
- USE_SYNC_INGEST (run synchronously when set to a truthy value)
- DJANGO_SECRET_KEY, ALLOWED_HOSTS, DEBUG

Notes:
- settings.py also reads `.env` automatically using django-environ.
- ALLOWED_HOSTS must include your host when DEBUG=false.

### 3) Apply migrations

From the Django project root (wikipedia_ingestion_backend):
```
python manage.py migrate
```

### 4) Run the development server

```
python manage.py runserver 0.0.0.0:8000
```

- Health check: http://localhost:8000/api/health/
- API docs (live schema):
  - Swagger UI: http://localhost:8000/docs
  - ReDoc: http://localhost:8000/redoc
  - Raw schema: http://localhost:8000/swagger.json

### 5) Optional: Generate a static OpenAPI file

This command computes absolute URLs based on the provided host/scheme/base path and writes to interfaces/openapi.json:
```
python manage.py generate_openapi --host localhost:8000 --scheme http --base-path /api
# Output: wikipedia_ingestion_backend/interfaces/openapi.json
```

## Using the API

Base path: /api

- Health: GET /api/health/
- Upload CSV for ingestion: POST /api/ingest/upload-csv/ (multipart/form-data; field name: csv_file)
- Single value ingestion: POST /api/ingest/single/ (JSON; {"value": "Alan Turing"})
- Job status: GET /api/ingest/jobs/{job_id}/
- Job items: GET /api/ingest/jobs/{job_id}/items/

Standard response envelope used across endpoints:
- success: boolean
- job_id: integer when applicable
- status: job status
- counts: total, processed, succeeded, failed when applicable
- error/detail: context-specific information

## Embeddings providers

- Default: sentence-transformers
  - The first run downloads the model specified by SENTENCE_TRANSFORMERS_MODEL (default: all-MiniLM-L6-v2).
  - No API key required; runs locally.
- Optional: OpenAI
  - Set EMBEDDINGS_PROVIDER=openai and provide OPENAI_API_KEY (and optionally OPENAI_EMBEDDINGS_MODEL).
  - The openai package must be installed in your environment.

If embeddings fail at runtime, the pipeline logs the error and continues without storing embeddings on the Chunk nodes.

## Guidance for constrained environments

If you cannot spawn threads or want deterministic request behavior, enable synchronous ingestion by setting:
- USE_SYNC_INGEST=true

This causes ingestion to complete within the API request. Expect longer request durations.

## Troubleshooting

- Neo4j connectivity/auth
  - Ensure NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD are set correctly.
  - Verify the instance is reachable from the application host and ports are open.
  - For encrypted connections (neo4j+s://), ensure certificates and networking are configured.

- Wikipedia fetch timeouts/slow responses
  - Increase REQUEST_TIMEOUT (seconds) in your .env if pages regularly time out.
  - Some topics or pages may be large or slow; retries are built-in but limited.

- Embeddings/model download issues
  - On first use, sentence-transformers will download a small model; ensure internet connectivity.
  - For OpenAI embeddings, verify OPENAI_API_KEY is set and the environment has `openai` installed.

- ALLOWED_HOSTS errors in production
  - Include your domain or IP in ALLOWED_HOSTS when DEBUG=false.

- Background execution behavior
  - Set MAX_WORKERS to control concurrency.
  - If resource constrained or deploying in environments that restrict threading, set USE_SYNC_INGEST=true.

## Project layout

- wikipedia_ingestion_backend/: Django project root
  - config/: Django settings and URL routing
  - api/: Models, views, services, tasks, and utilities
  - interfaces/: Generated OpenAPI specs

## Health and API docs quick links

Once the server is running locally:
- Health: http://localhost:8000/api/health/
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Swagger JSON: http://localhost:8000/swagger.json
