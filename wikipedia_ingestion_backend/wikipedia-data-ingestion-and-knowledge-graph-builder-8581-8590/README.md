# wikipedia-data-ingestion-and-knowledge-graph-builder-8581-8590

Django backend for uploading CSVs of Wikipedia topics/links, processing content via a RAG pipeline, and ingesting into Neo4j.

Key endpoints (prefixed with /api):
- Health: GET /api/health/
- Upload CSV: POST /api/ingest/upload-csv/
- Single ingest: POST /api/ingest/single/
- Job status: GET /api/ingest/jobs/{job_id}/
- Job items: GET /api/ingest/jobs/{job_id}/items/

API documentation:
- Swagger UI: /docs
- ReDoc: /redoc
- Raw schema: /swagger.json

Project layout:
- wikipedia_ingestion_backend/: Django project root
  - config/: Django project config and settings
  - api/: Application containing models, services, and views
  - interfaces/: Generated OpenAPI specs

## Quick start

1) Create and populate an environment file

From the Django project root (wikipedia_ingestion_backend/), copy the example:
```
cp .env.example .env
```

Edit `.env` as needed. Minimum required for full ingestion:
- NEO4J_URI
- NEO4J_USER
- NEO4J_PASSWORD

Optional but recommended:
- EMBEDDINGS_PROVIDER (defaults to sentence-transformers)
- For OpenAI embeddings: OPENAI_API_KEY and optional OPENAI_EMBEDDINGS_MODEL

2) Install dependencies (prefer a virtual environment)
```
cd wikipedia_ingestion_backend
pip install -r requirements.txt
```

3) Apply migrations and run the server
```
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

Visit:
- http://localhost:8000/docs for Swagger UI
- http://localhost:8000/redoc for ReDoc
- http://localhost:8000/swagger.json for the raw schema

4) Generate OpenAPI schema file (optional)
```
python manage.py generate_openapi --host localhost:8000 --scheme http --base-path /api
# Output written to: wikipedia_ingestion_backend/interfaces/openapi.json
```

## Environment variables

Required (for ingestion):
- NEO4J_URI: e.g., bolt://localhost:7687 or neo4j+s://<host>
- NEO4J_USER
- NEO4J_PASSWORD

Django/runtime:
- DJANGO_SECRET_KEY: Required in production, defaults to a dev key.
- DEBUG: true/false; default false.
- ALLOWED_HOSTS: comma-separated hostnames; default covers localhost and testserver.

RAG/embeddings:
- EMBEDDINGS_PROVIDER: "sentence-transformers" (default) or "openai"
- OPENAI_API_KEY: required only if EMBEDDINGS_PROVIDER=openai
- OPENAI_EMBEDDINGS_MODEL: optional override; default text-embedding-3-small

Chunking/timeouts:
- RAG_CHUNK_SIZE: default 1000
- RAG_CHUNK_OVERLAP: default 150
- REQUEST_TIMEOUT: default 60 (seconds)

Background execution:
- MAX_WORKERS: default 4
- USE_SYNC_INGEST: if "true"/"1", runs ingestion synchronously (no background threads)

Docs generation helpers (optional):
- SITE_HOST: host in generated docs (default testserver)
- SITE_SCHEME: http|https

An example `.env` is provided at `wikipedia_ingestion_backend/.env.example`.

## Running ingestion

- Upload a CSV with "csv_file" in a multipart/form-data POST to /api/ingest/upload-csv/.
- Or POST JSON to /api/ingest/single/ with:
```
{
  "value": "Alan Turing"
}
```
Responses include a standardized envelope with job_id and counts. Poll:
- GET /api/ingest/jobs/{job_id}/
- GET /api/ingest/jobs/{job_id}/items/

## Notes

- SQLite is used for Django metadata; Neo4j is used for the knowledge graph.
- If running with EMBEDDINGS_PROVIDER=openai, ensure OPENAI_API_KEY is set in the environment.
- For local embeddings, sentence-transformers will download a small model on first use.
