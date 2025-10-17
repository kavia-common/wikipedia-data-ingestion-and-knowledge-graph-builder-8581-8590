import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework.permissions import AllowAny


class Command(BaseCommand):
    help = "Generate OpenAPI schema (Swagger JSON) and write to interfaces/openapi.json"

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            type=str,
            default=os.environ.get("SITE_HOST", "testserver"),
            help="Hostname to embed in docs (defaults to SITE_HOST env or 'testserver')",
        )
        parser.add_argument(
            "--scheme",
            type=str,
            default=os.environ.get("SITE_SCHEME", "http"),
            choices=["http", "https"],
            help="URL scheme to embed in docs (default http)",
        )
        parser.add_argument(
            "--base-path",
            type=str,
            default="/api",
            help="Base path for API endpoints (default /api)",
        )

    def handle(self, *args, **options):
        # Build a request with desired host/scheme so drf-yasg computes absolute URLs correctly
        host = options["host"]
        scheme = options["scheme"]
        base_path = (options["base_path"] or "/").rstrip("/") or "/"

        # Ensure the RequestFactory request carries the proper metadata
        factory = RequestFactory()
        # path must exist under the configured API base to ensure resolver picks API urls
        path = f"{base_path}/?format=openapi" if base_path != "/" else "/?format=openapi"
        django_request = factory.get(path, secure=(scheme == "https"))
        django_request.META["HTTP_HOST"] = host
        if scheme == "https":
            django_request.META["HTTP_X_FORWARDED_PROTO"] = "https"

        # Configure a schema view with accurate meta information
        schema_view = get_schema_view(
            openapi.Info(
                title="Wikipedia Ingestion API",
                default_version="v1",
                description=(
                    "API for uploading CSVs of Wikipedia topics/links and ingesting content into a Neo4j "
                    "knowledge graph using RAG chunking and embeddings."
                ),
                contact=openapi.Contact(email="support@example.com"),
                license=openapi.License(name="MIT License"),
            ),
            public=True,
            permission_classes=(AllowAny,),
            url=f"{scheme}://{host}",
        )

        # Generate schema without UI
        response = schema_view.without_ui(cache_timeout=0)(django_request)
        response.render()

        try:
            openapi_schema = json.loads(response.content.decode())
        except Exception:
            # If response is already dict-like (unlikely), fallback
            openapi_schema = response.data

        # Some deployments prefer explicit basePath for swagger 2.0 generation
        # When present and different from "/", set it for clarity
        if isinstance(openapi_schema, dict):
            # If 'basePath' is not present, add it (drf-yasg often includes it)
            if "basePath" not in openapi_schema:
                openapi_schema["basePath"] = base_path

        # Write to interfaces/openapi.json at project root for interface discovery
        output_dir = os.path.join(settings.BASE_DIR, "interfaces")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "openapi.json")

        with open(output_path, "w") as f:
            json.dump(openapi_schema, f, indent=2)

        self.stdout.write(self.style.SUCCESS(f"OpenAPI schema written to {output_path}"))
