from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APITestCase

from incidents.models import Flight, Incident, IncidentEvent
from incidents.roles import OPERATOR_GROUP, TEAM_LEAD_GROUP
from incidents.services import assign_incident, create_incident, resolve_incident, start_incident


class IncidentWorkflowTests(APITestCase):
    def workflow_snapshot(self):
        return (
            list(Incident.objects.order_by("pk").values()),
            list(IncidentEvent.objects.order_by("pk").values()),
        )

    def setUp(self):
        self.team_leads = Group.objects.get(name=TEAM_LEAD_GROUP)
        self.operators = Group.objects.get(name=OPERATOR_GROUP)
        self.lead = User.objects.create_user(username="lead", password="test-password")
        self.lead.groups.add(self.team_leads)
        self.operator = User.objects.create_user(username="operator", password="test-password")
        self.operator.groups.add(self.operators)
        self.other_operator = User.objects.create_user(
            username="other-operator",
            password="test-password",
        )
        self.other_operator.groups.add(self.operators)
        departure = timezone.now() + timedelta(days=2)
        self.flight = Flight.objects.create(
            flight_number="FO401",
            departure_airport_code="JFK",
            arrival_airport_code="LHR",
            scheduled_departure=departure,
            scheduled_arrival=departure + timedelta(hours=7),
        )

    def create_incident(self):
        self.client.force_authenticate(self.lead)
        response = self.client.post(
            "/api/incidents/",
            {
                "flight": self.flight.pk,
                "kind": "CANCELLATION",
                "description": "Aircraft technical issue",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def test_cancellation_workflow_records_actor_and_status_at_each_step(self):
        incident_id = self.create_incident()
        incident = Incident.objects.get(pk=incident_id)
        self.assertEqual(incident.status, Incident.Status.OPEN)
        self.assertEqual(incident.events.count(), 1)

        self.client.force_authenticate(self.lead)
        response = self.client.post(
            f"/api/incidents/{incident_id}/assign/",
            {"operator_id": self.operator.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        incident.refresh_from_db()
        self.assertEqual(incident.assigned_to, self.operator)
        self.assertEqual(incident.events.count(), 2)

        self.client.force_authenticate(self.operator)
        response = self.client.post(f"/api/incidents/{incident_id}/start/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        incident.refresh_from_db()
        self.assertEqual(incident.status, Incident.Status.IN_PROGRESS)
        self.assertEqual(incident.events.count(), 3)

        response = self.client.post(
            f"/api/incidents/{incident_id}/resolve/",
            {"resolution_notes": "Replacement aircraft dispatched; passengers rebooked."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        incident.refresh_from_db()
        self.assertEqual(incident.status, Incident.Status.RESOLVED)
        self.assertEqual(
            incident.resolution_notes,
            "Replacement aircraft dispatched; passengers rebooked.",
        )

        response = self.client.get(f"/api/incidents/{incident_id}/events/")
        self.assertEqual(response.status_code, 200, response.data)
        events = response.data
        self.assertEqual([event["event_type"] for event in events], [
            "CREATED",
            "ASSIGNED",
            "STARTED",
            "RESOLVED",
        ])
        self.assertEqual([event["actor"] for event in events], [
            "lead",
            "lead",
            "operator",
            "operator",
        ])
        self.assertEqual(
            [(event["previous_status"], event["new_status"]) for event in events],
            [
                (None, "OPEN"),
                ("OPEN", "OPEN"),
                ("OPEN", "IN_PROGRESS"),
                ("IN_PROGRESS", "RESOLVED"),
            ],
        )
        self.assertTrue(all(event["created_at"] for event in events))

    def test_operator_cannot_create_an_incident(self):
        self.client.force_authenticate(self.operator)
        response = self.client.post(
            "/api/incidents/",
            {
                "flight": self.flight.pk,
                "kind": "DELAY",
                "description": "Unexpected turnaround delay",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Incident.objects.count(), 0)
        self.assertEqual(IncidentEvent.objects.count(), 0)

    def test_token_authentication_runs_the_full_cancellation_workflow(self):
        self.client.force_authenticate(user=None)
        tokens = {}
        for user in (self.lead, self.operator):
            response = self.client.post(
                "/api/auth/token/",
                {"username": user.username, "password": "test-password"},
                format="json",
            )
            self.assertEqual(response.status_code, 200, response.data)
            tokens[user.username] = response.data["token"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {tokens['lead']}")
        response = self.client.post("/api/flights/", {
            "flight_number": "FO402",
            "departure_airport_code": "JFK",
            "arrival_airport_code": "LHR",
            "scheduled_departure": "2026-12-02T10:00:00Z",
            "scheduled_arrival": "2026-12-02T22:00:00Z",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        response = self.client.post("/api/incidents/", {
            "flight": response.data["id"], "kind": "CANCELLATION",
            "description": "Aircraft technical issue",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        url = f"/api/incidents/{response.data['id']}/"
        self.assertEqual(self.client.post(
            url + "assign/", {"operator_id": self.operator.pk}, format="json",
        ).status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {tokens['operator']}")
        self.assertEqual(self.client.post(url + "start/", {}, format="json").status_code, 200)
        response = self.client.post(url + "resolve/", {
            "resolution_notes": "Passengers rebooked.",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "RESOLVED")
        events = self.client.get(url + "events/").data
        self.assertEqual([event["actor"] for event in events],
                         ["lead", "lead", "operator", "operator"])
        self.assertEqual([(event["previous_status"], event["new_status"]) for event in events],
                         [(None, "OPEN"), ("OPEN", "OPEN"),
                          ("OPEN", "IN_PROGRESS"), ("IN_PROGRESS", "RESOLVED")])

    def test_rejected_requests_preserve_all_incident_and_event_fields(self):
        incident_id = self.create_incident()
        url = f"/api/incidents/{incident_id}/"

        def reject(user, action, payload, expected):
            self.client.force_authenticate(user=user)
            before = self.workflow_snapshot()
            response = self.client.post(url + action + "/", payload, format="json")
            self.assertEqual(response.status_code, expected, response.data)
            self.assertEqual(self.workflow_snapshot(), before)

        for action, payload in (
            ("assign", {"operator_id": self.operator.pk}),
            ("start", {}), ("resolve", {"resolution_notes": "Done"}),
        ):
            reject(None, action, payload, 401)
            reject(self.other_operator, action, payload, 403 if action == "assign" else 404)
        reject(self.lead, "start", {}, 400)
        reject(self.lead, "resolve", {"resolution_notes": "Too early"}, 400)
        reject(self.lead, "assign", {"operator_id": self.lead.pk}, 400)
        assign_incident(incident_id=incident_id, actor=self.lead, operator=self.operator)
        reject(self.operator, "assign", {"operator_id": self.other_operator.pk}, 403)
        start_incident(incident_id=incident_id, actor=self.operator)
        reject(self.operator, "start", {}, 400)
        reject(self.lead, "assign", {"operator_id": self.other_operator.pk}, 400)
        for payload in ({}, {"resolution_notes": "   "}):
            reject(self.operator, "resolve", payload, 400)
        resolve_incident(incident_id=incident_id, actor=self.operator, resolution_notes="Done")
        reject(self.operator, "resolve", {"resolution_notes": "Again"}, 400)
        reject(self.lead, "start", {}, 400)
        reject(self.lead, "assign", {"operator_id": self.other_operator.pk}, 400)
        self.client.force_authenticate(self.lead)
        for method in (self.client.put, self.client.patch):
            before = self.workflow_snapshot()
            self.assertEqual(method(url, {"status": "OPEN"}, format="json").status_code, 405)
            self.assertEqual(self.workflow_snapshot(), before)

    def test_audit_write_failure_rolls_back_each_workflow_operation(self):
        before = self.workflow_snapshot()
        with patch("incidents.services.IncidentEvent.objects.create", side_effect=RuntimeError("Audit failure")):
            with self.assertRaises(RuntimeError):
                create_incident(validated_data={
                    "flight": self.flight, "kind": "CANCELLATION", "description": "Technical issue",
                }, actor=self.lead)
        self.assertEqual(self.workflow_snapshot(), before)
        incident_id = self.create_incident()
        operations = [
            lambda: assign_incident(incident_id=incident_id, actor=self.lead, operator=self.operator),
            lambda: start_incident(incident_id=incident_id, actor=self.operator),
            lambda: resolve_incident(incident_id=incident_id, actor=self.operator, resolution_notes="Done"),
        ]
        for operation in operations:
            before = self.workflow_snapshot()
            with patch("incidents.services.IncidentEvent.objects.create", side_effect=RuntimeError("Audit failure")):
                with self.assertRaises(RuntimeError):
                    operation()
            self.assertEqual(self.workflow_snapshot(), before)
            operation()

    def test_schema_describes_workflow_payloads_and_public_token_exchange(self):
        from drf_spectacular.generators import SchemaGenerator
        from drf_spectacular.validation import validate_schema

        schema = SchemaGenerator().get_schema(request=None, public=True)
        validate_schema(schema)
        paths = schema["paths"]
        self.assertFalse(paths["/api/auth/token/"]["post"].get("security"))
        for action, serializer in (("assign", "Assignment"), ("resolve", "Resolution")):
            request = paths[f"/api/incidents/{{id}}/{action}/"]["post"]["requestBody"]
            self.assertEqual(request["content"]["application/json"]["schema"]["$ref"],
                             f"#/components/schemas/{serializer}")
        self.assertNotIn("requestBody", paths["/api/incidents/{id}/start/"]["post"])
        events = paths["/api/incidents/{id}/events/"]["get"]["responses"]["200"]
        self.assertEqual(events["content"]["application/json"]["schema"]["items"]["$ref"],
                         "#/components/schemas/IncidentEvent")
        self.assertEqual({p["name"] for p in paths["/api/incidents/"]["get"]["parameters"]},
                         {"status", "kind"})

    def test_operator_cannot_read_incident_assigned_to_someone_else(self):
        incident_id = self.create_incident()
        self.client.force_authenticate(self.lead)
        self.client.post(
            f"/api/incidents/{incident_id}/assign/",
            {"operator_id": self.operator.pk},
            format="json",
        )

        self.client.force_authenticate(self.other_operator)
        list_response = self.client.get("/api/incidents/")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data, [])
        self.assertEqual(self.client.get(f"/api/incidents/{incident_id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/incidents/{incident_id}/events/").status_code, 404)

    def test_operator_cannot_assign_and_denial_changes_nothing(self):
        incident_id = self.create_incident()
        before = list(
            IncidentEvent.objects.filter(incident_id=incident_id).values_list(
                "event_type",
                "actor_id",
            )
        )
        self.client.force_authenticate(self.operator)
        response = self.client.post(
            f"/api/incidents/{incident_id}/assign/",
            {"operator_id": self.operator.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        incident = Incident.objects.get(pk=incident_id)
        self.assertEqual(incident.status, Incident.Status.OPEN)
        self.assertIsNone(incident.assigned_to)
        self.assertEqual(
            list(
                IncidentEvent.objects.filter(incident_id=incident_id).values_list(
                    "event_type",
                    "actor_id",
                )
            ),
            before,
        )

    def test_invalid_transition_and_missing_resolution_notes_are_atomic(self):
        incident_id = self.create_incident()
        self.client.force_authenticate(self.lead)
        response = self.client.post(
            f"/api/incidents/{incident_id}/resolve/",
            {"resolution_notes": "Cannot resolve before work starts."},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        incident = Incident.objects.get(pk=incident_id)
        self.assertEqual(incident.status, Incident.Status.OPEN)
        self.assertEqual(incident.events.count(), 1)

        self.client.post(
            f"/api/incidents/{incident_id}/assign/",
            {"operator_id": self.operator.pk},
            format="json",
        )
        self.client.force_authenticate(self.operator)
        self.client.post(f"/api/incidents/{incident_id}/start/", {}, format="json")
        response = self.client.post(
            f"/api/incidents/{incident_id}/resolve/",
            {"resolution_notes": "   "},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        incident.refresh_from_db()
        self.assertEqual(incident.status, Incident.Status.IN_PROGRESS)
        self.assertEqual(incident.resolution_notes, "")
        self.assertEqual(incident.events.count(), 3)

    def test_flight_number_can_repeat_on_another_day_but_same_departure_is_unique(self):
        Flight.objects.create(
            flight_number=self.flight.flight_number,
            departure_airport_code="JFK",
            arrival_airport_code="LHR",
            scheduled_departure=self.flight.scheduled_departure + timedelta(days=1),
            scheduled_arrival=self.flight.scheduled_arrival + timedelta(days=1),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Flight.objects.create(
                flight_number=self.flight.flight_number,
                departure_airport_code="JFK",
                arrival_airport_code="LHR",
                scheduled_departure=self.flight.scheduled_departure,
                scheduled_arrival=self.flight.scheduled_arrival,
            )
