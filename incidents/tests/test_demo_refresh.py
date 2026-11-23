from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase
from django.utils import timezone

from incidents.models import Flight, Incident
from incidents.serializers import IncidentSerializer
from incidents.services import assign_incident, create_incident, resolve_incident, start_incident


class DemoRefreshTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.lead = User.objects.create_user('teamlead')
        self.lead.groups.add(Group.objects.get_or_create(name='Team Leads')[0])
        self.operator = User.objects.create_user('operator', password='Demo-password!')
        self.operator.groups.add(Group.objects.get_or_create(name='Operators')[0])
        descriptions = ['Technical issue; rebooking required.',
                        'Operasyon paneli do?rulamas?: teknik ar?za nedeniyle iptal.',
                        'Operasyon paneli doğrulaması: teknik arıza nedeniyle iptal.']
        for index, description in enumerate(descriptions):
            departure = timezone.now() + timedelta(days=1, hours=index)
            flight = Flight.objects.create(flight_number=f'FO{index}', departure_airport_code='IST',
                arrival_airport_code='ADB', scheduled_departure=departure,
                scheduled_arrival=departure + timedelta(hours=1))
            item = create_incident(actor=self.lead, validated_data={
                'flight': flight, 'kind': 'CANCELLATION', 'description': description})
            assign_incident(incident_id=item.pk, actor=self.lead, operator=self.operator)
            start_incident(incident_id=item.pk, actor=self.operator)
            resolve_incident(incident_id=item.pk, actor=self.operator, resolution_notes='Test')
        call_command('create_demo_operations', stdout=StringIO())

    def test_refresh_preserves_counts_varies_times_and_distributes_shared_work(self):
        flights = list(Flight.objects.order_by('pk').values())
        call_command('refresh_demo_operations', stdout=StringIO())
        self.assertEqual(list(Flight.objects.order_by('pk').values()), flights)
        self.assertFalse(Incident.objects.filter(pk__in=[1, 2, 3]).exists())
        self.assertEqual(Incident.objects.count(), 20)
        self.assertEqual(Incident.objects.filter(status='RESOLVED').count(), 6)
        operators = User.objects.filter(groups__name='Operators')
        self.assertEqual(operators.count(), 5)
        for user in operators:
            self.assertTrue(user.check_password('Demo-password!'))
            self.assertGreater(user.assigned_incidents.count() + user.supported_incidents.count(), 1)
        self.assertTrue(Incident.objects.filter(supporting_operators__isnull=False).exists())
        waiting = []
        ordered = list(Incident.objects.order_by('-created_at'))
        self.assertEqual({item.flight.flight_number for item in ordered[-3:]}, {'DM1018', 'DM1019', 'DM1020'})
        for item in ordered:
            events = list(item.events.all())
            self.assertEqual(events[0].created_at, item.created_at)
            self.assertEqual(events[-1].created_at, item.updated_at)
            self.assertLessEqual(item.updated_at, timezone.now())
            self.assertEqual(events[-1].new_status, item.status)
            if item.status != 'OPEN':
                waiting.append(IncidentSerializer(item).data['waiting_seconds'])
            if item.assigned_to_id:
                names = IncidentSerializer(item).data['assigned_operators']
                self.assertEqual(item.events.get(event_type='ASSIGNED').details['assigned_operators'], names)
        self.assertEqual(len(set(waiting)), len(waiting))
        before = list(Incident.objects.order_by('pk').values())
        call_command('refresh_demo_operations', stdout=StringIO())
        self.assertEqual(list(Incident.objects.order_by('pk').values()), before)

    def test_unknown_first_record_prevents_any_changes(self):
        Incident.objects.filter(pk=1).update(description='User data')
        before = list(Incident.objects.order_by('pk').values())
        with self.assertRaises(CommandError):
            call_command('refresh_demo_operations', stdout=StringIO())
        self.assertEqual(list(Incident.objects.order_by('pk').values()), before)
        self.assertEqual(User.objects.count(), 2)
