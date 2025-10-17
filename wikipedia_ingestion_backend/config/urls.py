"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from django.views.decorators.csrf import csrf_exempt

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
]

# Central schema information
API_INFO = openapi.Info(
    title="Wikipedia Ingestion API",
    default_version="v1",
    description=(
        "Endpoints for uploading CSVs of topics/links, processing Wikipedia content, "
        "chunking and embedding text, and ingesting into a Neo4j knowledge graph."
    ),
    contact=openapi.Contact(email="support@example.com"),
    license=openapi.License(name="MIT License"),
)

schema_view = get_schema_view(
    API_INFO,
    public=True,
    permission_classes=(permissions.AllowAny,),
)

def get_full_url(request):
    scheme = request.scheme
    host = request.get_host()
    forwarded_port = request.META.get("HTTP_X_FORWARDED_PORT")

    if ':' not in host and forwarded_port:
        host = f"{host}:{forwarded_port}"

    return f"{scheme}://{host}"

@csrf_exempt
def dynamic_schema_view(request, *args, **kwargs):
    """
    Dynamic Swagger UI that sets the absolute URL based on the incoming request.
    This ensures correct schema host when running behind proxies or in CI.
    """
    url = get_full_url(request)
    view = get_schema_view(
        API_INFO,
        public=True,
        url=url,
    )
    return view.with_ui('swagger', cache_timeout=0)(request)

urlpatterns += [
    re_path(r'^docs/$', dynamic_schema_view, name='schema-swagger-ui'),
    re_path(r'^redoc/$', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    re_path(r'^swagger\.json$', schema_view.without_ui(cache_timeout=0), name='schema-json'),
]