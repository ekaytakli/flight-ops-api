from django.contrib.auth import get_user_model
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
            "created_by",
            "assigned_to",
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
        source="operator",
        queryset=User.objects.filter(
            groups__name="Operators",
            is_active=True,
        ).distinct(),
    )


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
