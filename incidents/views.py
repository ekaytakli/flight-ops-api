from django.contrib.auth import get_user_model
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Flight, Incident, IncidentEvent
from .permissions import IsTeamLead, IsTeamLeadOrAssignedOperator, IsTeamLeadOrOperator
from .roles import is_operator, is_team_lead
from .serializers import (
    AssignmentSerializer,
    CurrentUserSerializer,
    FlightSerializer,
    IncidentEventSerializer,
    IncidentSerializer,
    ResolutionSerializer,
    OperatorSerializer,
)
from .services import assign_incident, create_incident, resolve_incident, start_incident


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated, IsTeamLeadOrOperator]

    @extend_schema(responses=CurrentUserSerializer)
    def get(self, request):
        return Response({
            "id": request.user.pk,
            "username": request.user.username,
            "role": "team_lead" if is_team_lead(request.user) else "operator",
        })


class OperatorListView(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = OperatorSerializer
    permission_classes = [IsAuthenticated, IsTeamLead]
    queryset = get_user_model().objects.filter(
        groups__name="Operators", is_active=True,
    ).distinct().order_by("username")


class FlightViewSet(viewsets.ModelViewSet):
    queryset = Flight.objects.all()
    serializer_class = FlightSerializer
    permission_classes = [IsAuthenticated, IsTeamLead]


@extend_schema_view(
    list=extend_schema(parameters=[
        OpenApiParameter("status", str, enum=Incident.Status.values),
        OpenApiParameter("kind", str, enum=Incident.Kind.values),
    ]),
)
class IncidentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = IncidentSerializer
    permission_classes = [
        IsAuthenticated,
        IsTeamLeadOrOperator,
        IsTeamLeadOrAssignedOperator,
    ]

    def get_queryset(self):
        queryset = Incident.objects.select_related("flight", "created_by", "assigned_to")
        if is_team_lead(self.request.user):
            pass
        elif is_operator(self.request.user):
            queryset = queryset.filter(assigned_to=self.request.user)
        else:
            return queryset.none()

        incident_status = self.request.query_params.get("status")
        incident_kind = self.request.query_params.get("kind")
        if incident_status:
            queryset = queryset.filter(status=incident_status.upper())
        if incident_kind:
            queryset = queryset.filter(kind=incident_kind.upper())
        return queryset

    def get_permissions(self):
        if self.action in ("create", "assign"):
            return [permission() for permission in (IsAuthenticated, IsTeamLead)]
        return super().get_permissions()

    def perform_create(self, serializer):
        serializer.instance = create_incident(
            validated_data=serializer.validated_data,
            actor=self.request.user,
        )

    @extend_schema(responses=IncidentEventSerializer(many=True))
    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        incident = self.get_object()
        events = incident.events.select_related("actor").all()
        return Response(IncidentEventSerializer(events, many=True).data)

    @extend_schema(request=AssignmentSerializer, responses=IncidentSerializer)
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        incident = self.get_object()
        if not is_team_lead(request.user):
            raise PermissionDenied("Only team leads can assign incidents.")
        serializer = AssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        incident = assign_incident(
            incident_id=incident.pk,
            actor=request.user,
            operator=serializer.validated_data["operator"],
        )
        return Response(self.get_serializer(incident).data)

    @extend_schema(request=None, responses=IncidentSerializer)
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        incident = self.get_object()
        incident = start_incident(incident_id=incident.pk, actor=request.user)
        return Response(self.get_serializer(incident).data)

    @extend_schema(request=ResolutionSerializer, responses=IncidentSerializer)
    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        incident = self.get_object()
        serializer = ResolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        incident = resolve_incident(
            incident_id=incident.pk,
            actor=request.user,
            resolution_notes=serializer.validated_data["resolution_notes"],
        )
        return Response(self.get_serializer(incident).data)
