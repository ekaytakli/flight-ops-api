from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from incidents.models import Flight, Incident, IncidentEvent
from incidents.services import assign_incident, create_incident, resolve_incident, start_incident


class DemoOperationsTests(TestCase):
    def setUp(self):
        self.lead = User.objects.create_user(username="teamlead")
        self.lead.groups.add(Group.objects.get(name="Team Leads"))
        self.operator = User.objects.create_user(username="operator")
        self.operator.groups.add(Group.objects.get(name="Operators"))
        departure = timezone.now() - timedelta(days=1)
        for index in range(3):
            flight = Flight.objects.create(
                flight_number=f"TK{index}", departure_airport_code="IST", arrival_airport_code="LHR",
                scheduled_departure=departure + timedelta(hours=index),
                scheduled_arrival=departure + timedelta(hours=index + 4),
            )
            incident = create_incident(actor=self.lead, validated_data={
                "flight": flight, "kind": "CANCELLATION", "description": "Existing record",
            })
            assign_incident(incident_id=incident.pk, actor=self.lead, operator=self.operator)
            start_incident(incident_id=incident.pk, actor=self.operator)
            resolve_incident(incident_id=incident.pk, actor=self.operator, resolution_notes="Existing resolution")
        call_command("create_demo_flights", stdout=StringIO())

    def snapshot(self):
        return (list(Flight.objects.order_by("pk").values()),
                list(Incident.objects.order_by("pk").values()),
                list(IncidentEvent.objects.order_by("pk").values()))

    def test_expands_103_to_200_with_ten_percent_affected_and_preserves_existing_records(self):
        before = self.snapshot()
        call_command("create_demo_operations", stdout=StringIO())
        self.assertEqual(Flight.objects.count(), 200)
        self.assertEqual(Incident.objects.count(), 20)
        self.assertEqual(Incident.objects.values("flight_id").distinct().count(), 20)
        self.assertEqual(Incident.objects.filter(status="OPEN").count(), 8)
        self.assertEqual(Incident.objects.filter(status="IN_PROGRESS").count(), 6)
        self.assertEqual(Incident.objects.filter(status="RESOLVED").count(), 6)
        after = self.snapshot()
        for original, current in zip(before, after):
            current_by_id = {row["id"]: row for row in current}
            self.assertTrue(all(row == current_by_id[row["id"]] for row in original))
        new = Incident.objects.exclude(pk__in=[row["id"] for row in before[1]])
        self.assertEqual(new.values("description").distinct().count(), 17)
        self.assertEqual(set(new.values_list("kind", flat=True)), {"DELAY", "CANCELLATION"})
        self.assertEqual(set(new.values_list("priority", flat=True)), {"LOW", "NORMAL", "HIGH", "CRITICAL"})
        for incident in new:
            events = list(incident.events.all())
            self.assertEqual(events[0].event_type, "CREATED")
            self.assertEqual(events[0].created_at, incident.created_at)
            self.assertEqual(events[-1].created_at, incident.updated_at)
            self.assertLessEqual(incident.updated_at, timezone.now())
            self.assertEqual(events[-1].new_status, incident.status)
            if incident.status != "OPEN":
                self.assertEqual(incident.assigned_to, self.operator)
                self.assertTrue(any(event.event_type == "STARTED" for event in events))
            if incident.status == "RESOLVED":
                self.assertTrue(incident.resolution_notes)
        self.assertTrue(new.filter(status="OPEN", assigned_to__isnull=True).exists())
        self.assertTrue(new.filter(status="OPEN", assigned_to=self.operator).exists())
        call_command("create_demo_operations", stdout=StringIO())
        self.assertEqual(self.snapshot(), after)

    def test_audit_failure_rolls_back_flights_and_incidents_together(self):
        before = self.snapshot()
        with patch("incidents.services.IncidentEvent.objects.create", side_effect=RuntimeError("Audit failure")):
            with self.assertRaises(RuntimeError):
                call_command("create_demo_operations", stdout=StringIO())
        self.assertEqual(self.snapshot(), before)
