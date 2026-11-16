from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.routers import DefaultRouter

from incidents.views import CurrentUserView, FlightViewSet, IncidentViewSet, OperatorListView


@extend_schema(auth=[])
class PublicAuthTokenView(ObtainAuthToken):
    pass

router = DefaultRouter()
router.register("flights", FlightViewSet, basename="flight")
router.register("incidents", IncidentViewSet, basename="incident")
router.register("operators", OperatorListView, basename="operator")

urlpatterns = [
    path("", TemplateView.as_view(template_name="incidents/dashboard.html"), name="dashboard"),
    path("admin/", admin.site.urls),
    path("api/auth/token/", PublicAuthTokenView.as_view(), name="api-token-auth"),
    path("api/auth/me/", CurrentUserView.as_view(), name="current-user"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/", include(router.urls)),
]
