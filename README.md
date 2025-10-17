# wikipedia-data-ingestion-and-knowledge-graph-builder-8581-8590

Django backend for uploading CSVs of Wikipedia topics/links, processing content via a RAG pipeline, and ingesting into Neo4j.

API documentation:
- Swagger UI: /docs
- ReDoc: /redoc
- Raw schema: /swagger.json

Generate OpenAPI schema file:
- From project root: `python manage.py generate_openapi --host localhost:8000 --scheme http --base-path /api`
- Output: `wikipedia_ingestion_backend/interfaces/openapi.json`
