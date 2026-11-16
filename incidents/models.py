from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q


class Flight(models.Model):
    flight_number = models.CharField(max_length=8)
    departure_airport_code = models.CharField(
        max_length=3,
        validators=[RegexValidator(r"^[A-Z]{3}$", "Use a three-letter uppercase IATA code.")],
    )
    arrival_airport_code = models.CharField(
        max_length=3,
        validators=[RegexValidator(r"^[A-Z]{3}$", "Use a three-letter uppercase IATA code.")],
    )
    scheduled_departure = models.DateTimeField()
    scheduled_arrival = models.DateTimeField()

    class Meta:
        ordering = ["scheduled_departure", "flight_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["flight_number", "scheduled_departure"],
                name="unique_flight_number_scheduled_departure",
            ),
            models.CheckConstraint(
                condition=~Q(departure_airport_code=models.F("arrival_airport_code")),
                name="flight_airports_must_differ",
            ),
            models.CheckConstraint(
                condition=Q(scheduled_arrival__gt=models.F("scheduled_departure")),
                name="flight_arrival_after_departure",
            ),
        ]

    def __str__(self):
        return f"{self.flight_number} {self.scheduled_departure:%Y-%m-%d}"


class Incident(models.Model):
    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        NORMAL = "NORMAL", "Normal"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class Kind(models.TextChoices):
        DELAY = "DELAY", "Delay"
        CANCELLATION = "CANCELLATION", "Cancellation"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        RESOLVED = "RESOLVED", "Resolved"

    flight = models.ForeignKey(Flight, on_delete=models.PROTECT, related_name="incidents")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    description = models.TextField()
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_incidents",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_incidents",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    resolution_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} on {self.flight}"


class IncidentEvent(models.Model):
    class Type(models.TextChoices):
        CREATED = "CREATED", "Created"
        ASSIGNED = "ASSIGNED", "Assigned"
        STARTED = "STARTED", "Started"
        RESOLVED = "RESOLVED", "Resolved"
        PRIORITY_CHANGED = "PRIORITY_CHANGED", "Priority changed"

    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=16, choices=Type.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="incident_events",
    )
    previous_status = models.CharField(
        max_length=16,
        choices=Incident.Status.choices,
        null=True,
        blank=True,
    )
    new_status = models.CharField(
        max_length=16,
        choices=Incident.Status.choices,
        null=True,
        blank=True,
    )
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.event_type} by {self.actor}"
