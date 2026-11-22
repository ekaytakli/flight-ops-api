from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from incidents.models import Flight


class DemoFlightTests(TestCase):
    def test_seed_adds_varied_valid_flights_and_preserves_records_when_repeated(self):
        departure = timezone.now()
        existing = Flight.objects.create(
            flight_number="TK001", departure_airport_code="IST", arrival_airport_code="LHR",
            scheduled_departure=departure, scheduled_arrival=departure + timedelta(hours=4),
        )
        before = Flight.objects.values().get(pk=existing.pk)
        options = {"start_date": date(2026, 12, 1), "stdout": StringIO()}
        call_command("create_demo_flights", **options)
        self.assertEqual(Flight.objects.count(), 101)
        demo = Flight.objects.exclude(pk=existing.pk)
        self.assertEqual(demo.values("departure_airport_code", "arrival_airport_code").distinct().count(), 100)
        self.assertEqual(demo.values("arrival_airport_code").distinct().count(), 20)
        for flight in demo:
            flight.full_clean()
        snapshot = list(Flight.objects.order_by("pk").values())
        call_command("create_demo_flights", **options)
        self.assertEqual(list(Flight.objects.order_by("pk").values()), snapshot)
        self.assertEqual(Flight.objects.values().get(pk=existing.pk), before)

    def test_invalid_count_does_not_write_any_flights(self):
        for count in (0, -1, 10001):
            with self.subTest(count=count), self.assertRaises(CommandError):
                call_command("create_demo_flights", count=count, stdout=StringIO())
        self.assertFalse(Flight.objects.exists())
