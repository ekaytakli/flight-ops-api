from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.utils import timezone
from rest_framework.test import APITestCase

from incidents.models import Flight, Incident, IncidentEvent
from incidents.services import create_incident


class FlightDeletionTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lead = User.objects.create_user(username="deletion-lead")
        cls.lead.groups.add(Group.objects.get(name="Team Leads"))
        cls.operator = User.objects.create_user(username="deletion-operator")
        cls.operator.groups.add(Group.objects.get(name="Operators"))
        departure = timezone.now() + timedelta(days=1)
        cls.flight = Flight.objects.create(
            flight_number="TK601",
            departure_airport_code="IST",
            arrival_airport_code="LHR",
            scheduled_departure=departure,
            scheduled_arrival=departure + timedelta(hours=4),
        )

    def setUp(self):
        self.path = f"/api/flights/{self.flight.pk}/"

    def test_team_lead_can_delete_a_flight_without_incidents(self):
        self.client.force_authenticate(self.lead)
        response = self.client.delete(self.path)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Flight.objects.filter(pk=self.flight.pk).exists())
        self.assertEqual(self.client.delete(self.path).status_code, 404)

    def test_linked_incidents_block_deletion_and_preserve_all_records(self):
        incident = create_incident(
            validated_data={
                "flight": self.flight, "kind": "DELAY", "description": "Technical issue",
            },
            actor=self.lead,
        )
        self.client.force_authenticate(self.lead)
        for status in Incident.Status.values:
            with self.subTest(status=status):
                Incident.objects.filter(pk=incident.pk).update(status=status)
                before = (
                    list(Flight.objects.values()),
                    list(Incident.objects.values()),
                    list(IncidentEvent.objects.values()),
                )
                response = self.client.delete(self.path)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(
                    response.json(),
                    {"detail": "Flights with incidents cannot be deleted."},
                )
                self.assertEqual(before, (
                    list(Flight.objects.values()),
                    list(Incident.objects.values()),
                    list(IncidentEvent.objects.values()),
                ))

    def test_deletion_requires_a_team_lead(self):
        for user, expected in ((None, 401), (self.operator, 403)):
            with self.subTest(user=user):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.delete(self.path).status_code, expected)
                self.assertTrue(Flight.objects.filter(pk=self.flight.pk).exists())
