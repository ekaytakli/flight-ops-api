from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.utils import timezone
from rest_framework.test import APITestCase

from incidents.models import Flight
from incidents.roles import OPERATOR_GROUP, TEAM_LEAD_GROUP
from incidents.services import assign_incident, create_incident


class DashboardTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lead = User.objects.create_user(username="dashboard-lead")
        cls.lead.groups.add(Group.objects.get(name=TEAM_LEAD_GROUP))
        cls.operator = User.objects.create_user(username="dashboard-operator")
        cls.operator.groups.add(Group.objects.get(name=OPERATOR_GROUP))
        cls.inactive = User.objects.create_user(username="inactive-operator", is_active=False)
        cls.inactive.groups.add(Group.objects.get(name=OPERATOR_GROUP))
        cls.outsider = User.objects.create_user(username="no-role")
        departure = timezone.now() + timedelta(days=3)
        cls.flight = Flight.objects.create(
            flight_number="TK900", departure_airport_code="IST", arrival_airport_code="LHR",
            scheduled_departure=departure, scheduled_arrival=departure + timedelta(hours=4),
        )

    def test_dashboard_is_public_but_contains_no_credentials_or_incident_data(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'lang="tr"')
        self.assertContains(response, "incidents/dashboard.js")
        self.assertNotContains(response, 'class="route-art"')
        self.assertNotContains(response, self.lead.username)
        self.assertNotContains(response, self.flight.flight_number)

    def test_current_user_requires_authentication_and_an_operations_role(self):
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        for user, role in ((self.lead, "team_lead"), (self.operator, "operator")):
            self.client.force_authenticate(user)
            response = self.client.get("/api/auth/me/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, {"id": user.pk, "username": user.username, "role": role})
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 403)

    def test_only_team_leads_can_list_active_operators_without_sensitive_fields(self):
        self.assertEqual(self.client.get("/api/operators/").status_code, 401)
        self.client.force_authenticate(self.operator)
        self.assertEqual(self.client.get("/api/operators/").status_code, 403)
        self.client.force_authenticate(self.lead)
        response = self.client.get("/api/operators/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [{
            "id": self.operator.pk, "username": self.operator.username,
            "first_name": "", "last_name": "",
        }])
        self.assertEqual(self.client.post("/api/operators/", {}).status_code, 405)

    def test_assigned_operator_sees_flight_details_only_through_scoped_incidents(self):
        incident = create_incident(validated_data={
            "flight": self.flight, "kind": "CANCELLATION", "description": "Technical issue",
        }, actor=self.lead)
        self.client.force_authenticate(self.operator)
        self.assertEqual(self.client.get("/api/incidents/").data["results"], [])
        self.assertEqual(self.client.get(f"/api/incidents/{incident.pk}/").status_code, 404)
        assign_incident(incident_id=incident.pk, actor=self.lead, operator=self.operator)
        response = self.client.get(f"/api/incidents/{incident.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["flight_details"]["flight_number"], "TK900")
        self.assertEqual(self.client.get("/api/flights/").status_code, 403)
        self.client.force_authenticate(self.lead)
        response = self.client.post("/api/incidents/", {
            "flight": self.flight.pk, "kind": "DELAY", "description": "Turnaround",
            "flight_details": {"flight_number": "OVERRIDE"},
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.flight.refresh_from_db()
        self.assertEqual(self.flight.flight_number, "TK900")
