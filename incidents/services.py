from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import Incident, IncidentEvent
from .roles import is_operator, is_team_lead


@transaction.atomic
def assign_incident(*, incident_id, actor, operator):
    incident = Incident.objects.select_for_update().get(pk=incident_id)
    if not is_team_lead(actor):
        raise PermissionDenied("Only team leads can assign incidents.")
    if incident.status != Incident.Status.OPEN:
        raise ValidationError({"status": "Only open incidents can be assigned."})
    if not is_operator(operator) or not operator.is_active:
        raise ValidationError({"operator_id": "Select an active user in the Operators group."})

    previous_operator = incident.assigned_to
    incident.assigned_to = operator
    incident.save(update_fields=["assigned_to", "updated_at"])
    IncidentEvent.objects.create(
        incident=incident,
        event_type=IncidentEvent.Type.ASSIGNED,
        actor=actor,
        previous_status=incident.status,
        new_status=incident.status,
        details={
            "previous_operator": previous_operator.username if previous_operator else None,
            "assigned_operator": operator.username,
        },
    )
    return incident


@transaction.atomic
def start_incident(*, incident_id, actor):
    incident = Incident.objects.select_for_update().get(pk=incident_id)
    if not (is_team_lead(actor) or (is_operator(actor) and incident.assigned_to_id == actor.id)):
        raise PermissionDenied("Only the assigned operator or a team lead can start this incident.")
    if incident.status != Incident.Status.OPEN:
        raise ValidationError({"status": "Only open incidents can be started."})
    if incident.assigned_to_id is None:
        raise ValidationError({"assigned_to": "Assign an operator before starting work."})

    incident.status = Incident.Status.IN_PROGRESS
    incident.save(update_fields=["status", "updated_at"])
    IncidentEvent.objects.create(
        incident=incident,
        event_type=IncidentEvent.Type.STARTED,
        actor=actor,
        previous_status=Incident.Status.OPEN,
        new_status=Incident.Status.IN_PROGRESS,
    )
    return incident


@transaction.atomic
def resolve_incident(*, incident_id, actor, resolution_notes):
    incident = Incident.objects.select_for_update().get(pk=incident_id)
    if not (is_team_lead(actor) or (is_operator(actor) and incident.assigned_to_id == actor.id)):
        raise PermissionDenied("Only the assigned operator or a team lead can resolve this incident.")
    if incident.status != Incident.Status.IN_PROGRESS:
        raise ValidationError({"status": "Only in-progress incidents can be resolved."})
    if not resolution_notes or not resolution_notes.strip():
        raise ValidationError({"resolution_notes": "Resolution notes are required."})

    incident.status = Incident.Status.RESOLVED
    incident.resolution_notes = resolution_notes.strip()
    incident.save(update_fields=["status", "resolution_notes", "updated_at"])
    IncidentEvent.objects.create(
        incident=incident,
        event_type=IncidentEvent.Type.RESOLVED,
        actor=actor,
        previous_status=Incident.Status.IN_PROGRESS,
        new_status=Incident.Status.RESOLVED,
        details={"resolution_notes": incident.resolution_notes},
    )
    return incident


@transaction.atomic
def create_incident(*, validated_data, actor):
    incident = Incident.objects.create(created_by=actor, **validated_data)
    IncidentEvent.objects.create(
        incident=incident,
        event_type=IncidentEvent.Type.CREATED,
        actor=actor,
        new_status=incident.status,
        details={"kind": incident.kind},
    )
    return incident
