from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from incidents.models import Flight, Incident, IncidentEvent
from incidents.serializers import IncidentSerializer
from incidents.services import assign_incident, change_priority, create_incident, start_incident


class ImprovementTests(APITestCase):
    def setUp(self):
        cache.clear()

    @classmethod
    def setUpTestData(cls):
        cls.lead = User.objects.create_user(username="lead-new", password="Current-Password-2026!")
        cls.lead.groups.add(Group.objects.get(name="Team Leads"))
        cls.operator = User.objects.create_user(username="operator-new")
        cls.operator.groups.add(Group.objects.get(name="Operators"))
        departure = timezone.now() + timedelta(days=2)
        cls.flight = Flight.objects.create(
            flight_number="TK501", departure_airport_code="IST", arrival_airport_code="LHR",
            scheduled_departure=departure, scheduled_arrival=departure + timedelta(hours=4),
        )

    def incident(self, priority="NORMAL"):
        return create_incident(validated_data={
            "flight": self.flight, "kind": "DELAY", "description": "Turnaround issue", "priority": priority,
        }, actor=self.lead)

    def snapshot(self):
        return (list(Incident.objects.order_by("pk").values()),
                list(IncidentEvent.objects.order_by("pk").values()))

    def test_priority_creation_change_audit_and_rollback(self):
        self.client.force_authenticate(self.lead)
        response = self.client.post("/api/incidents/", {
            "flight": self.flight.pk, "kind": "DELAY", "description": "Issue", "priority": "CRITICAL",
        })
        self.assertEqual(response.status_code, 201)
        incident = Incident.objects.get(pk=response.data["id"])
        self.assertEqual(incident.events.get().details["priority"], "CRITICAL")
        response = self.client.post(f"/api/incidents/{incident.pk}/priority/", {"priority": "HIGH"})
        self.assertEqual(response.status_code, 200)
        event = incident.events.last()
        self.assertEqual(event.actor, self.lead)
        self.assertEqual(event.details, {"previous_priority": "CRITICAL", "priority": "HIGH"})
        self.assertEqual((event.previous_status, event.new_status), ("OPEN", "OPEN"))
        before = self.snapshot()
        change_priority(incident_id=incident.pk, actor=self.lead, priority="HIGH")
        self.assertEqual(before, self.snapshot())
        with patch("incidents.services.IncidentEvent.objects.create", side_effect=RuntimeError("Audit failure")):
            with self.assertRaises(RuntimeError):
                change_priority(incident_id=incident.pk, actor=self.lead, priority="LOW")
        self.assertEqual(before, self.snapshot())
        for user, value, expected in ((self.operator, "LOW", 403), (self.lead, "INVALID", 400)):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.post(f"/api/incidents/{incident.pk}/priority/", {"priority": value}).status_code, expected)
            self.assertEqual(before, self.snapshot())
        incident.status = "RESOLVED"
        incident.save()
        before = self.snapshot()
        self.client.force_authenticate(self.lead)
        self.assertEqual(self.client.post(f"/api/incidents/{incident.pk}/priority/", {"priority": "LOW"}).status_code, 400)
        self.assertEqual(before, self.snapshot())

    def test_waiting_seconds_grows_until_start_then_remains_fixed(self):
        incident = self.incident()
        created = timezone.now() - timedelta(hours=2)
        Incident.objects.filter(pk=incident.pk).update(created_at=created)
        self.client.force_authenticate(self.lead)
        path = f"/api/incidents/{incident.pk}/"
        response = self.client.get(path)
        self.assertGreaterEqual(response.data["waiting_seconds"], 7200)
        assign_incident(incident_id=incident.pk, actor=self.lead, operator=self.operator)
        start_incident(incident_id=incident.pk, actor=self.operator)
        waiting = self.client.get(path).data["waiting_seconds"]
        with patch("incidents.serializers.timezone.now", return_value=timezone.now() + timedelta(days=1)):
            self.assertEqual(self.client.get(path).data["waiting_seconds"], waiting)
        self.assertIn("updated_at", response.data)

    def test_lifecycle_durations_use_events_and_stop_at_resolution(self):
        incident = self.incident()
        now = timezone.now().replace(microsecond=0)
        created = now - timedelta(days=2)
        started = created + timedelta(minutes=20)
        resolved = started + timedelta(hours=3)
        Incident.objects.filter(pk=incident.pk).update(created_at=created)
        self.client.force_authenticate(self.lead)
        path = f"/api/incidents/{incident.pk}/"

        def assert_durations(waiting, processing, total):
            detail = self.client.get(path).data
            listing = self.client.get("/api/incidents/").data["results"][0]
            incident.refresh_from_db()
            direct = IncidentSerializer(incident).data
            for result in (detail, listing, direct):
                self.assertEqual(result["waiting_seconds"], waiting)
                self.assertEqual(result["processing_seconds"], processing)
                self.assertEqual(result["total_seconds"], total)
            return detail

        with patch("incidents.serializers.timezone.now", return_value=now):
            opened = assert_durations(172800, 0, 172800)
            self.assertIsNone(opened["started_at"])
            assign_incident(incident_id=incident.pk, actor=self.lead, operator=self.operator)
            response = self.client.post(path + "start/", {})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["processing_seconds"], 0)
            incident.events.filter(event_type="STARTED").update(created_at=started)
            # A later administrative update must not reset the processing clock.
            change_priority(incident_id=incident.pk, actor=self.lead, priority="HIGH")
            working = assert_durations(1200, 171600, 172800)
            self.assertIsNotNone(working["started_at"])
            self.assertIsNone(working["resolved_at"])
            response = self.client.post(path + "resolve/", {"resolution_notes": "Fixed"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["total_seconds"], 172800)
            incident.events.filter(event_type="RESOLVED").update(created_at=resolved)
            closed = assert_durations(1200, 10800, 12000)
            self.assertIsNotNone(closed["resolved_at"])
        with patch("incidents.serializers.timezone.now", return_value=now + timedelta(days=7)):
            assert_durations(1200, 10800, 12000)

    def test_missing_history_does_not_invent_work_or_resolution_times(self):
        incident = self.incident()
        incident.status = "IN_PROGRESS"
        incident.save()
        data = IncidentSerializer(incident).data
        self.assertIsNone(data["waiting_seconds"])
        self.assertIsNone(data["processing_seconds"])
        self.assertIsNotNone(data["total_seconds"])
        incident.status = "RESOLVED"
        incident.save()
        data = IncidentSerializer(incident).data
        self.assertIsNone(data["total_seconds"])
        self.assertIsNone(data["resolved_at"])

    def test_historical_out_of_order_times_never_produce_negative_durations(self):
        incident = self.incident()
        now = timezone.now()
        incident.status = "IN_PROGRESS"
        incident.created_at = now - timedelta(hours=1)
        incident.save()
        event = IncidentEvent.objects.create(incident=incident, actor=self.lead, event_type="STARTED")
        for started in (now + timedelta(hours=1), now - timedelta(hours=2)):
            IncidentEvent.objects.filter(pk=event.pk).update(created_at=started)
            with patch("incidents.serializers.timezone.now", return_value=now):
                data = IncidentSerializer(incident).data
            self.assertGreaterEqual(data["waiting_seconds"], 0)
            self.assertGreaterEqual(data["processing_seconds"], 0)
            self.assertEqual(data["waiting_seconds"] + data["processing_seconds"], data["total_seconds"])

    def test_repeated_assignment_preserves_timestamp_and_audit_history(self):
        incident = self.incident()
        self.client.force_authenticate(self.lead)
        path = f"/api/incidents/{incident.pk}/assign/"
        payload = {"operator_id": self.operator.pk}
        self.assertEqual(self.client.post(path, payload).status_code, 200)
        before = self.snapshot()
        self.assertEqual(self.client.post(path, payload).status_code, 200)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(incident.events.filter(event_type="ASSIGNED").count(), 1)
        start_incident(incident_id=incident.pk, actor=self.operator)
        before = self.snapshot()
        self.assertEqual(self.client.post(path, payload).status_code, 400)
        self.assertEqual(self.snapshot(), before)

    def test_pagination_semantic_priority_order_and_scoped_summary(self):
        records = {value: self.incident(value) for value in Incident.Priority.values}
        self.client.force_authenticate(self.lead)
        response = self.client.get("/api/incidents/?ordering=-priority&page_size=2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 4)
        self.assertEqual([row["priority"] for row in response.data["results"]], ["CRITICAL", "HIGH"])
        self.assertIsNotNone(response.data["next"])
        response = self.client.get("/api/incidents/?ordering=-priority&page_size=2&page=2")
        self.assertEqual([row["priority"] for row in response.data["results"]], ["NORMAL", "LOW"])
        self.assertEqual(self.client.get("/api/incidents/?priority=HIGH&search=TK501").data["count"], 1)
        self.assertEqual(self.client.get("/api/incidents/?search=nonexistent").data["count"], 0)
        self.assertEqual(self.client.get("/api/incidents/?page=99").status_code, 404)
        self.assertEqual(self.client.get("/api/incidents/summary/?status=RESOLVED").data,
                         {"total": 4, "open": 4, "in_progress": 0, "resolved": 0})
        assigned = records["HIGH"]
        assign_incident(incident_id=assigned.pk, actor=self.lead, operator=self.operator)
        self.client.force_authenticate(self.operator)
        self.assertEqual(self.client.get("/api/incidents/?page_size=1").data["count"], 1)
        self.assertEqual(self.client.get("/api/incidents/summary/").data["total"], 1)
        self.assertEqual(self.client.get("/api/incidents/?search=nonexistent").data["count"], 0)
        self.assertEqual(self.client.get(f"/api/incidents/{assigned.pk}/?status=RESOLVED").status_code, 200)

    def test_team_lead_can_edit_flight_with_validation_while_operator_cannot(self):
        path = f"/api/flights/{self.flight.pk}/"
        self.client.force_authenticate(self.operator)
        self.assertEqual(self.client.patch(path, {"flight_number": "TK502"}).status_code, 403)
        self.client.force_authenticate(self.lead)
        self.assertEqual(self.client.patch(path, {"arrival_airport_code": "IST"}).status_code, 400)
        self.assertEqual(self.client.patch(path, {"scheduled_arrival": self.flight.scheduled_departure.isoformat()}).status_code, 400)
        self.assertEqual(self.client.patch(path, {"flight_number": "TK502"}).status_code, 200)
        self.assertEqual(self.client.get("/api/flights/?search=TK502").data["count"], 1)

    def authenticate_token(self):
        token = Token.objects.create(user=self.lead)
        self.client.credentials(HTTP_AUTHORIZATION="Token " + token.key)
        return token.key

    def test_logout_revokes_token_on_server(self):
        self.authenticate_token()
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.assertFalse(Token.objects.filter(user=self.lead).exists())

    def test_password_change_rejects_invalid_requests_and_revokes_token_on_success(self):
        self.authenticate_token()
        for old, new in (("wrong", "New-Secure-Password-2026!"),
                         ("Current-Password-2026!", "123"),
                         ("Current-Password-2026!", "Current-Password-2026!")):
            self.assertEqual(self.client.post("/api/auth/password/", {"old_password": old, "new_password": new}).status_code, 400)
            self.lead.refresh_from_db()
            self.assertTrue(self.lead.check_password("Current-Password-2026!"))
            self.assertTrue(Token.objects.filter(user=self.lead).exists())
        self.assertEqual(self.client.post("/api/auth/password/", {
            "old_password": "Current-Password-2026!", "new_password": "New-Secure-Password-2026!",
        }).status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.client.credentials()
        self.assertEqual(self.client.post("/api/auth/token/", {"username": self.lead.username, "password": "Current-Password-2026!"}).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/token/", {"username": self.lead.username, "password": "New-Secure-Password-2026!"}).status_code, 200)

    def test_auth_actions_require_a_token(self):
        for endpoint in ("logout", "password"):
            self.assertEqual(self.client.post(f"/api/auth/{endpoint}/", {}).status_code, 401)

    def test_password_change_rolls_back_if_token_revocation_fails(self):
        self.authenticate_token()
        with patch("incidents.views.Token.objects.filter") as tokens:
            tokens.return_value.delete.side_effect = RuntimeError("Token store failure")
            with self.assertRaises(RuntimeError):
                self.client.post("/api/auth/password/", {
                    "old_password": "Current-Password-2026!", "new_password": "New-Secure-Password-2026!",
                })
        self.lead.refresh_from_db()
        self.assertTrue(self.lead.check_password("Current-Password-2026!"))
        self.assertTrue(Token.objects.filter(user=self.lead).exists())

    def test_page_size_is_capped_and_tied_ordering_has_no_duplicates(self):
        Incident.objects.bulk_create([
            Incident(flight=self.flight, kind="DELAY", description="Pagination", created_by=self.lead)
            for _ in range(105)
        ])
        Incident.objects.all().update(created_at=timezone.now())
        self.client.force_authenticate(self.lead)
        first = self.client.get("/api/incidents/?page_size=999&ordering=created_at").data
        second = self.client.get("/api/incidents/?page_size=999&ordering=created_at&page=2").data
        self.assertEqual(first["count"], 105)
        self.assertEqual(len(first["results"]), 100)
        self.assertEqual(len(second["results"]), 5)
        ids = [row["id"] for row in first["results"] + second["results"]]
        self.assertEqual(len(set(ids)), 105)
        self.assertEqual(ids, sorted(ids))

    def test_invalid_priority_does_not_create_incident_or_audit_event(self):
        self.client.force_authenticate(self.lead)
        response = self.client.post("/api/incidents/", {
            "flight": self.flight.pk, "kind": "DELAY", "description": "Issue", "priority": "INVALID",
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Incident.objects.exists())
        self.assertFalse(IncidentEvent.objects.exists())
