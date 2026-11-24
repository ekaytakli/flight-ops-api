from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Case, Count, IntegerField, OuterRef, Q, Subquery, Value, When
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view, inline_serializer
from rest_framework import mixins, serializers, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.filters import SearchFilter
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Flight, FlightAuditEvent, Incident, IncidentEvent
from .exceptions import FlightDeletionConflict
from .filters import IncidentOrderingFilter, StableOrderingFilter
from .pagination import OperationsPagination
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
    PasswordChangeSerializer,
    PrioritySerializer,
    IncidentSummarySerializer,
)
from .services import assign_incident, change_priority, create_incident, resolve_incident, start_incident


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


class LogoutView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        request.auth.delete()
        return Response(status=204)


class PasswordChangeView(APIView):
    @extend_schema(request=PasswordChangeSerializer, responses={204: None})
    @transaction.atomic
    def post(self, request):
        user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        serializer = PasswordChangeSerializer(data=request.data, context={"user": user})
        serializer.is_valid(raise_exception=True)
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        Token.objects.filter(user=user).delete()
        return Response(status=204)


@extend_schema_view(
    destroy=extend_schema(responses={
        204: None,
        409: inline_serializer(
            name="FlightDeletionConflict",
            fields={"detail": serializers.CharField(read_only=True)},
        ),
    }),
)
class FlightViewSet(viewsets.ModelViewSet):
    queryset = Flight.objects.all()
    serializer_class = FlightSerializer
    permission_classes = [IsAuthenticated, IsTeamLead]
    pagination_class = OperationsPagination
    filter_backends = [SearchFilter, StableOrderingFilter]
    search_fields = ["flight_number", "departure_airport_code", "arrival_airport_code"]
    ordering_fields = ["scheduled_departure", "scheduled_arrival", "flight_number", "id"]
    ordering = ["scheduled_departure", "id"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action in ("update", "partial_update", "destroy"):
            return queryset.select_for_update()
        return queryset

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    @transaction.atomic
    def perform_create(self, serializer):
        flight = serializer.save()
        FlightAuditEvent.objects.create(
            flight_identifier=flight.pk, event_type=FlightAuditEvent.Type.CREATED,
            actor=self.request.user, after=dict(FlightSerializer(flight).data),
        )

    def perform_update(self, serializer):
        before = dict(FlightSerializer(serializer.instance).data)
        flight = serializer.save()
        after = dict(FlightSerializer(flight).data)
        if before != after:
            FlightAuditEvent.objects.create(
                flight_identifier=flight.pk, event_type=FlightAuditEvent.Type.UPDATED,
                actor=self.request.user, before=before, after=after,
            )

    def perform_destroy(self, instance):
        before = dict(FlightSerializer(instance).data)
        try:
            instance.delete()
        except ProtectedError as error:
            raise FlightDeletionConflict() from error
        FlightAuditEvent.objects.create(
            flight_identifier=before["id"], event_type=FlightAuditEvent.Type.DELETED,
            actor=self.request.user, before=before,
        )


@extend_schema_view(
    list=extend_schema(parameters=[
        OpenApiParameter("status", str, enum=Incident.Status.values),
        OpenApiParameter("kind", str, enum=Incident.Kind.values),
        OpenApiParameter("priority", str, enum=Incident.Priority.values),
    ]),
)
class IncidentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = IncidentSerializer
    pagination_class = OperationsPagination
    filter_backends = [SearchFilter, IncidentOrderingFilter]
    search_fields = ["flight__flight_number", "flight__departure_airport_code", "flight__arrival_airport_code", "description", "assigned_to__username", "supporting_operators__username"]
    ordering_fields = ["created_at", "updated_at", "priority", "flight__flight_number", "id"]
    ordering = ["-created_at", "-pk"]
    permission_classes = [
        IsAuthenticated,
        IsTeamLeadOrOperator,
        IsTeamLeadOrAssignedOperator,
    ]

    def get_queryset(self):
        started = IncidentEvent.objects.filter(
            incident_id=OuterRef("pk"), event_type=IncidentEvent.Type.STARTED,
        ).order_by("created_at", "pk").values("created_at")[:1]
        resolved = IncidentEvent.objects.filter(
            incident_id=OuterRef("pk"), event_type=IncidentEvent.Type.RESOLVED,
        ).order_by("created_at", "pk").values("created_at")[:1]
        queryset = Incident.objects.select_related("flight", "created_by", "assigned_to").prefetch_related("supporting_operators").annotate(
            work_started_at=Subquery(started),
            work_resolved_at=Subquery(resolved),
            priority_rank=Case(
                *[When(priority=value, then=Value(rank)) for rank, value in enumerate(Incident.Priority.values)],
                default=Value(1), output_field=IntegerField(),
            ),
        )
        if is_team_lead(self.request.user):
            pass
        elif is_operator(self.request.user):
            queryset = queryset.filter(Q(assigned_to=self.request.user) | Q(supporting_operators=self.request.user)).distinct()
        else:
            return queryset.none()

        if self.action != "list":
            return queryset
        for field in ("status", "kind", "priority"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field: value.upper()})
        return queryset

    def get_permissions(self):
        if self.action in ("create", "assign", "priority"):
            return [permission() for permission in (IsAuthenticated, IsTeamLead)]
        return super().get_permissions()

    def perform_create(self, serializer):
        serializer.instance = create_incident(
            validated_data=serializer.validated_data,
            actor=self.request.user,
        )

    @extend_schema(responses=IncidentSummarySerializer, filters=False)
    @action(detail=False, methods=["get"], pagination_class=None)
    def summary(self, request):
        counts = self.get_queryset().aggregate(
            total=Count("pk"), open=Count("pk", filter=Q(status=Incident.Status.OPEN)),
            in_progress=Count("pk", filter=Q(status=Incident.Status.IN_PROGRESS)),
            resolved=Count("pk", filter=Q(status=Incident.Status.RESOLVED)),
        )
        return Response(counts)

    @extend_schema(request=PrioritySerializer, responses=IncidentSerializer)
    @action(detail=True, methods=["post"])
    def priority(self, request, pk=None):
        incident = self.get_object()
        serializer = PrioritySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        incident = change_priority(incident_id=incident.pk, actor=request.user,
                                   priority=serializer.validated_data["priority"])
        return Response(self.get_serializer(incident).data)

    @extend_schema(responses=IncidentEventSerializer(many=True))
    @action(detail=True, methods=["get"], filter_backends=[], pagination_class=None)
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
            **serializer.validated_data,
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
