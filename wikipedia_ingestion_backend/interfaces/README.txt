This directory contains interface specifications generated from the running Django app.

To regenerate OpenAPI/Swagger schema:
    python manage.py generate_openapi --host <host> --scheme <http|https> --base-path /api

The command writes openapi.json into this folder.
