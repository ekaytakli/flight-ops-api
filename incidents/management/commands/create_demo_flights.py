from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from math import asin, ceil, cos, radians, sin, sqrt

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from incidents.models import Flight


# Coordinates are used only to estimate durations for synthetic demo flights.
AIRPORTS = (
    ("IST", 41.28, 28.75), ("ESB", 40.12, 32.99), ("ADB", 38.29, 27.16),
    ("AYT", 36.90, 30.80), ("DLM", 36.71, 28.79), ("TZX", 41.00, 39.79),
    ("LHR", 51.47, -0.45), ("CDG", 49.01, 2.55), ("FRA", 50.04, 8.56),
    ("AMS", 52.31, 4.76), ("FCO", 41.80, 12.25), ("MAD", 40.47, -3.56),
    ("ATH", 37.94, 23.94), ("VIE", 48.11, 16.57), ("DXB", 25.25, 55.36),
    ("DOH", 25.27, 51.61), ("JFK", 40.64, -73.78), ("SIN", 1.36, 103.99),
    ("NRT", 35.77, 140.39), ("BKK", 13.69, 100.75),
)


def demo_duration(origin, destination):
    lat1, lon1 = map(radians, origin[1:])
    lat2, lon2 = map(radians, destination[1:])
    arc = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    distance = 2 * 6371 * asin(sqrt(min(1, arc)))
    minutes = max(45, ceil((distance / 800 * 60 + 30) / 5) * 5)
    return timedelta(minutes=minutes)


def demo_flight_data(index, start):
    origin_index = index % len(AIRPORTS)
    offset = 1 + (index // len(AIRPORTS)) % (len(AIRPORTS) - 1)
    origin = AIRPORTS[origin_index]
    destination = AIRPORTS[(origin_index + offset) % len(AIRPORTS)]
    departure = start + timedelta(hours=index * 2, minutes=(index % 4) * 15)
    return {
        "flight_number": f"DM{1001 + index}", "scheduled_departure": departure,
        "departure_airport_code": origin[0], "arrival_airport_code": destination[0],
        "scheduled_arrival": departure + demo_duration(origin, destination),
    }


class Command(BaseCommand):
    help = "Mevcut kayıtları koruyarak farklı güzergâhlarda sentetik demo uçuşları oluşturur."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=100)
        parser.add_argument("--start-date", type=date.fromisoformat, help="İlk kalkış günü (YYYY-MM-DD, UTC).")

    @transaction.atomic
    def handle(self, *args, **options):
        count = options["count"]
        if not 1 <= count <= 10000:
            raise CommandError("Uçuş sayısı 1 ile 10000 arasında olmalıdır.")
        start_date = options["start_date"] or timezone.localdate() + timedelta(days=1)
        start = datetime.combine(start_date, time(6), tzinfo=datetime_timezone.utc)
        created = 0
        for index in range(count):
            data = demo_flight_data(index, start)
            _, is_new = Flight.objects.get_or_create(
                flight_number=data.pop("flight_number"), scheduled_departure=data.pop("scheduled_departure"),
                defaults=data,
            )
            created += is_new
        self.stdout.write(self.style.SUCCESS(
            f"{created} demo uçuş eklendi, {count - created} mevcut demo uçuş korundu. "
            f"Toplam uçuş: {Flight.objects.count()}. Başlangıç: {start_date} (UTC)."
        ))
