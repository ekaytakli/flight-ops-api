from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from queue import Queue
from threading import Barrier
from time import monotonic, sleep

from django.contrib.auth.models import Group, User
from django.db import connection, connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from incidents.models import Flight, Incident, IncidentEvent
from incidents.services import assign_incident, create_incident, resolve_incident, start_incident


@skipUnlessDBFeature("has_select_for_update")
class IncidentConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.lead = User.objects.create_user(username="concurrent-lead")
        self.lead.groups.add(Group.objects.get_or_create(name="Team Leads")[0])
        self.operator = User.objects.create_user(username="concurrent-operator")
        self.other = User.objects.create_user(username="concurrent-other")
        operators = Group.objects.get_or_create(name="Operators")[0]
        self.operator.groups.add(operators)
        self.other.groups.add(operators)
        departure = timezone.now() + timedelta(days=1)
        flight = Flight.objects.create(
            flight_number="TK777", departure_airport_code="IST", arrival_airport_code="LHR",
            scheduled_departure=departure, scheduled_arrival=departure + timedelta(hours=4),
        )
        self.incident = create_incident(validated_data={
            "flight": flight, "kind": "CANCELLATION", "description": "Concurrent operations",
        }, actor=self.lead)
        assign_incident(incident_id=self.incident.pk, actor=self.lead, operator=self.operator)

    def race(self, operation):
        barrier = Barrier(2)

        def worker():
            try:
                actor = User.objects.get(pk=self.operator.pk)
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '8s'")
                barrier.wait(timeout=5)
                try:
                    operation(actor)
                    return "success"
                except ValidationError:
                    return "invalid_transition"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            outcomes = [future.result(timeout=12) for future in futures]
        self.assertCountEqual(outcomes, ["success", "invalid_transition"])

    def test_simultaneous_start_records_exactly_one_transition_and_event(self):
        self.race(lambda actor: start_incident(incident_id=self.incident.pk, actor=actor))
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, "IN_PROGRESS")
        self.assertEqual(self.incident.events.filter(event_type="STARTED").count(), 1)
        self.assertEqual(self.incident.events.count(), 3)

    def test_simultaneous_resolve_records_exactly_one_transition_and_event(self):
        start_incident(incident_id=self.incident.pk, actor=self.operator)
        self.race(lambda actor: resolve_incident(incident_id=self.incident.pk, actor=actor,
                                                 resolution_notes="Passengers rebooked"))
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, "RESOLVED")
        self.assertEqual(self.incident.resolution_notes, "Passengers rebooked")
        self.assertEqual(self.incident.events.filter(event_type="RESOLVED").count(), 1)
        self.assertEqual(self.incident.events.count(), 4)

    def test_start_waits_for_lock_and_rechecks_assignment_after_commit(self):
        backend_pid = Queue()

        def worker():
            try:
                actor = User.objects.get(pk=self.operator.pk)
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '8s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    backend_pid.put(cursor.fetchone()[0])
                try:
                    start_incident(incident_id=self.incident.pk, actor=actor)
                    return "unexpected_success"
                except PermissionDenied:
                    return "denied"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                Incident.objects.select_for_update().get(pk=self.incident.pk)
                future = executor.submit(worker)
                pid = backend_pid.get(timeout=5)
                deadline = monotonic() + 5
                blocked = False
                while monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_stat_clear_snapshot()")
                        cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [pid])
                        row = cursor.fetchone()
                    if row and row[0] == "Lock":
                        blocked = True
                        break
                    sleep(0.02)
                self.assertTrue(blocked, "Concurrent start did not wait for the PostgreSQL row lock")
                assign_incident(incident_id=self.incident.pk, actor=self.lead, operator=self.other)
            self.assertEqual(future.result(timeout=10), "denied")
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, "OPEN")
        self.assertEqual(self.incident.assigned_to, self.other)
        self.assertFalse(IncidentEvent.objects.filter(incident=self.incident, event_type="STARTED").exists())
