from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.utils import timezone
from rest_framework.test import APITestCase

from incidents.models import Flight, FlightAuditEvent
from incidents.services import create_incident


class FlightAuditTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lead = User.objects.create_user(username="audit-lead")
        cls.lead.groups.add(Group.objects.get(name="Team Leads"))
        cls.admin = User.objects.create_superuser("audit-admin", password="Audit-Test-2026!")

    def setUp(self):
        self.client.force_authenticate(self.lead)
        departure = timezone.now() + timedelta(days=2)
        self.payload = {
            "flight_number": "TK451", "departure_airport_code": "IST",
            "arrival_airport_code": "LHR", "scheduled_departure": departure.isoformat(),
            "scheduled_arrival": (departure + timedelta(hours=4)).isoformat(),
        }

    def create_flight(self):
        response = self.client.post("/api/flights/", self.payload, format="json")
        self.assertEqual(response.status_code, 201)
        return response.data["id"]

    def test_create_update_noop_and_delete_preserve_snapshots_and_actor(self):
        identifier = self.create_flight()
        path = f"/api/flights/{identifier}/"
        created = FlightAuditEvent.objects.get()
        self.assertEqual(created.event_type, "CREATED")
        self.assertEqual(created.actor, self.lead)
        self.assertEqual(created.before, {})
        self.assertEqual(created.after["flight_number"], "TK451")
        self.assertEqual(self.client.patch(path, {"flight_number": "TK452"}).status_code, 200)
        updated = FlightAuditEvent.objects.last()
        self.assertEqual(updated.event_type, "UPDATED")
        self.assertEqual(updated.before, created.after)
        self.assertEqual(updated.after["flight_number"], "TK452")
        self.assertEqual(self.client.patch(path, {"flight_number": "TK452"}).status_code, 200)
        self.assertEqual(FlightAuditEvent.objects.count(), 2)
        self.assertEqual(self.client.delete(path).status_code, 204)
        deleted = FlightAuditEvent.objects.last()
        self.assertEqual(deleted.event_type, "DELETED")
        self.assertEqual(deleted.flight_identifier, identifier)
        self.assertEqual(deleted.before, updated.after)
        self.assertEqual(deleted.after, {})
        self.assertFalse(Flight.objects.filter(pk=identifier).exists())

    def test_audit_failure_rolls_back_create_update_and_delete(self):
        identifier = self.create_flight()
        path = f"/api/flights/{identifier}/"
        for method, url, payload in (
            ("post", "/api/flights/", {**self.payload, "flight_number": "TK999"}),
            ("patch", path, {"flight_number": "TK999"}),
            ("delete", path, {}),
        ):
            with self.subTest(method=method):
                before = list(Flight.objects.values())
                with patch("incidents.views.FlightAuditEvent.objects.create", side_effect=RuntimeError("Audit unavailable")):
                    with self.assertRaises(RuntimeError):
                        getattr(self.client, method)(url, payload, format="json")
                self.assertEqual(list(Flight.objects.values()), before)
                self.assertEqual(FlightAuditEvent.objects.count(), 1)

    def test_invalid_update_and_protected_deletion_write_no_audit(self):
        identifier = self.create_flight()
        path = f"/api/flights/{identifier}/"
        self.assertEqual(self.client.patch(path, {"arrival_airport_code": "IST"}).status_code, 400)
        create_incident(validated_data={
            "flight": Flight.objects.get(pk=identifier), "kind": "DELAY", "description": "Test",
        }, actor=self.lead)
        self.assertEqual(self.client.delete(path).status_code, 409)
        self.assertEqual(FlightAuditEvent.objects.count(), 1)

    def test_admin_can_read_history_but_cannot_bypass_audited_workflow(self):
        identifier = self.create_flight()
        event = FlightAuditEvent.objects.get()
        self.client.force_login(self.admin)
        for model, pk in (("flight", identifier), ("flightauditevent", event.pk)):
            path = f"/admin/incidents/{model}/"
            self.assertEqual(self.client.get(path + f"{pk}/change/").status_code, 200)
            self.assertEqual(self.client.post(path + f"{pk}/change/", {}).status_code, 403)
            self.assertEqual(self.client.post(path + f"{pk}/delete/", {"post": "yes"}).status_code, 403)
            self.assertEqual(self.client.post(path + "add/", {}).status_code, 403)
        self.assertTrue(Flight.objects.filter(pk=identifier).exists())
        self.assertEqual(FlightAuditEvent.objects.count(), 1)
