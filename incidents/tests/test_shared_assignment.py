from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.utils import timezone
from rest_framework.test import APITestCase

from incidents.models import Flight, Incident
from incidents.services import assign_incident, create_incident


class SharedAssignmentTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lead = User.objects.create_user('shared-lead')
        cls.lead.groups.add(Group.objects.get(name='Team Leads'))
        cls.operators = [User.objects.create_user(f'shared-{i}') for i in range(3)]
        for user in cls.operators:
            user.groups.add(Group.objects.get(name='Operators'))
        departure = timezone.now() + timedelta(days=1)
        cls.flight = Flight.objects.create(flight_number='DM9000', departure_airport_code='IST',
            arrival_airport_code='ADB', scheduled_departure=departure,
            scheduled_arrival=departure + timedelta(hours=1))

    def setUp(self):
        self.incident = create_incident(actor=self.lead, validated_data={
            'flight': self.flight, 'kind': 'DELAY', 'description': 'Technical report'})

    def assign(self, users):
        self.client.force_authenticate(self.lead)
        return self.client.post(f'/api/incidents/{self.incident.pk}/assign/',
                                {'operator_ids': [user.pk for user in users]}, format='json')

    def test_both_operators_can_see_and_work_on_shared_incident(self):
        response = self.assign(self.operators[:2])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['assigned_operators'], [user.username for user in self.operators[:2]])
        for user in self.operators[:2]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get('/api/incidents/').data['count'], 1)
            self.assertEqual(self.client.get('/api/incidents/summary/').data['total'], 1)
            self.assertEqual(self.client.get(f'/api/incidents/{self.incident.pk}/events/').status_code, 200)
        self.client.force_authenticate(self.operators[2])
        self.assertEqual(self.client.get('/api/incidents/').data['count'], 0)
        self.assertEqual(self.client.post(f'/api/incidents/{self.incident.pk}/start/').status_code, 404)
        self.client.force_authenticate(self.operators[1])
        self.assertEqual(self.client.post(f'/api/incidents/{self.incident.pk}/start/').status_code, 200)
        self.client.force_authenticate(self.operators[0])
        self.assertEqual(self.client.post(f'/api/incidents/{self.incident.pk}/resolve/',
            {'resolution_notes': 'Operational coordination completed.'}).status_code, 200)

    def test_replacement_revokes_removed_operator_and_repeat_has_no_extra_event(self):
        self.assign(self.operators[:2])
        count = self.incident.events.count()
        self.assign(list(reversed(self.operators[:2])))
        self.assertEqual(self.incident.events.count(), count)
        self.client.force_authenticate(self.lead)
        response = self.client.post(f'/api/incidents/{self.incident.pk}/assign/',
            {'operator_id': self.operators[2].pk}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['assigned_operators'], [self.operators[2].username])
        self.client.force_authenticate(self.operators[1])
        self.assertEqual(self.client.get(f'/api/incidents/{self.incident.pk}/').status_code, 404)

    def test_invalid_assignment_and_audit_failure_preserve_original_team(self):
        self.assign(self.operators[:2])
        for users in ([], self.operators, [self.operators[0], self.operators[0]]):
            self.assertEqual(self.assign(users).status_code, 400)
        with patch('incidents.services.IncidentEvent.objects.create', side_effect=RuntimeError('Audit failed')):
            with self.assertRaises(RuntimeError):
                assign_incident(incident_id=self.incident.pk, actor=self.lead, operator=self.operators[2])
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.assigned_to, self.operators[0])
        self.assertEqual(list(self.incident.supporting_operators.all()), [self.operators[1]])
