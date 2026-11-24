from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.utils.translation import override
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Flight, Incident, IncidentEvent
from .roles import is_operator

User = get_user_model()


class FlightSerializer(serializers.ModelSerializer):
    class Meta:
        model = Flight
        fields = [
            "id",
            "flight_number",
            "departure_airport_code",
            "arrival_airport_code",
            "scheduled_departure",
            "scheduled_arrival",
        ]

    def validate(self, attrs):
        departure = attrs.get(
            "scheduled_departure",
            getattr(self.instance, "scheduled_departure", None),
        )
        arrival = attrs.get(
            "scheduled_arrival",
            getattr(self.instance, "scheduled_arrival", None),
        )
        origin = attrs.get(
            "departure_airport_code",
            getattr(self.instance, "departure_airport_code", None),
        )
        destination = attrs.get(
            "arrival_airport_code",
            getattr(self.instance, "arrival_airport_code", None),
        )
        errors = {}
        if departure and arrival and arrival <= departure:
            errors["scheduled_arrival"] = "Arrival must be after departure."
        if origin and destination and origin == destination:
            errors["arrival_airport_code"] = "Origin and destination must differ."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class IncidentSerializer(serializers.ModelSerializer):
    waiting_seconds = serializers.IntegerField(read_only=True, min_value=0, allow_null=True)
    processing_seconds = serializers.IntegerField(read_only=True, min_value=0, allow_null=True)
    total_seconds = serializers.IntegerField(read_only=True, min_value=0, allow_null=True)
    started_at = serializers.DateTimeField(read_only=True, allow_null=True)
    resolved_at = serializers.DateTimeField(read_only=True, allow_null=True)
    assigned_operators = serializers.SerializerMethodField()

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_assigned_operators(self, instance):
        return ([instance.assigned_to.username] if instance.assigned_to_id else []) + [
            user.username for user in instance.supporting_operators.all()
        ]

    def to_representation(self, instance):
        result = super().to_representation(instance)
        now = timezone.now()

        def event_time(annotation, event_type):
            if hasattr(instance, annotation):
                return getattr(instance, annotation)
            return instance.events.filter(event_type=event_type).order_by("created_at", "pk").values_list("created_at", flat=True).first()

        started = event_time("work_started_at", IncidentEvent.Type.STARTED) if instance.status != Incident.Status.OPEN else None
        resolved = event_time("work_resolved_at", IncidentEvent.Type.RESOLVED) if instance.status == Incident.Status.RESOLVED else None
        end = resolved if instance.status == Incident.Status.RESOLVED else now

        def seconds(begin, finish):
            return max(0, int((finish - begin).total_seconds())) if begin and finish else None

        # Use lifecycle events, never updated_at: assignment/priority changes are not work boundaries.
        # Keep the phases additive even when historical timestamps are out of order.
        work_start = max(instance.created_at, min(started, end)) if started and end else None
        total = seconds(instance.created_at, end)
        waiting = seconds(instance.created_at, now) if instance.status == Incident.Status.OPEN else seconds(instance.created_at, work_start)
        processing = 0 if instance.status == Incident.Status.OPEN else (total - waiting if total is not None and waiting is not None else None)
        result.update(
            waiting_seconds=waiting, processing_seconds=processing, total_seconds=total,
            started_at=self.fields["started_at"].to_representation(started) if started else None,
            resolved_at=self.fields["resolved_at"].to_representation(resolved) if resolved else None,
        )
        return result

    flight_details = FlightSerializer(source="flight", read_only=True)
    created_by = serializers.CharField(source="created_by.username", read_only=True)
    assigned_to = serializers.CharField(
        source="assigned_to.username",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = Incident
        fields = [
            "id",
            "flight",
            "flight_details",
            "kind",
            "description",
            "priority",
            "waiting_seconds",
            "processing_seconds",
            "total_seconds",
            "started_at",
            "resolved_at",
            "created_by",
            "assigned_to",
            "assigned_operators",
            "status",
            "resolution_notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "assigned_to",
            "status",
            "resolution_notes",
            "created_at",
            "updated_at",
        ]


class AssignmentSerializer(serializers.Serializer):
    operator_id = serializers.PrimaryKeyRelatedField(
        required=False,
        source="operator",
        queryset=User.objects.filter(
            groups__name="Operators",
            is_active=True,
        ).distinct(),
    )
    operator_ids = serializers.ListField(
        source="operators", required=False, min_length=1, max_length=2,
        child=serializers.PrimaryKeyRelatedField(
            queryset=User.objects.filter(groups__name="Operators", is_active=True).distinct(),
        ),
    )

    def validate(self, attrs):
        if ("operator" in attrs) == ("operators" in attrs):
            raise serializers.ValidationError("Provide operator_id or operator_ids.")
        selected = attrs.get("operators", [attrs.get("operator")])
        if not 1 <= len(selected) <= 2 or len({user.pk for user in selected}) != len(selected):
            raise serializers.ValidationError({"operator_ids": "Select one or two distinct operators."})
        return attrs


class ResolutionSerializer(serializers.Serializer):
    resolution_notes = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
        max_length=10000,
    )

    def validate_resolution_notes(self, value):
        if not value:
            raise serializers.ValidationError("Resolution notes are required.")
        return value


class IncidentEventSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.username", read_only=True)

    class Meta:
        model = IncidentEvent
        fields = [
            "id",
            "event_type",
            "actor",
            "previous_status",
            "new_status",
            "details",
            "created_at",
        ]


class OperatorSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name"]
        read_only_fields = fields


class CurrentUserSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    role = serializers.ChoiceField(choices=["team_lead", "operator"], read_only=True)


class PrioritySerializer(serializers.Serializer):
    priority = serializers.ChoiceField(choices=Incident.Priority.choices)


class IncidentSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField(read_only=True)
    open = serializers.IntegerField(read_only=True)
    in_progress = serializers.IntegerField(read_only=True)
    resolved = serializers.IntegerField(read_only=True)


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        user = self.context["user"]
        if not user.check_password(attrs["old_password"]):
            raise serializers.ValidationError({"old_password": "Mevcut parola yanlış."})
        if attrs["old_password"] == attrs["new_password"]:
            raise serializers.ValidationError({"new_password": "Yeni parola mevcut paroladan farklı olmalıdır."})
        try:
            with override("tr"):
                validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"new_password": error.messages})
        return attrs
