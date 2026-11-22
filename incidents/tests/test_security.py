import os
import subprocess
import sys
import textwrap
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from incidents.models import Flight, Incident, IncidentEvent
from incidents.services import create_incident
from incidents.throttles import LoginRateThrottle


class IncidentAdminSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("security-admin", password="Admin-Test-2026!")
        departure = timezone.now() + timedelta(days=1)
        flight = Flight.objects.create(
            flight_number="TK101", departure_airport_code="IST", arrival_airport_code="LHR",
            scheduled_departure=departure, scheduled_arrival=departure + timedelta(hours=4),
        )
        cls.incident = create_incident(validated_data={
            "flight": flight, "kind": "DELAY", "description": "Audit protection",
        }, actor=cls.admin)

    def test_admin_can_inspect_incident_and_history_but_cannot_mutate_them(self):
        self.client.force_login(self.admin)
        path = f"/admin/incidents/incident/{self.incident.pk}/"
        before = (list(Incident.objects.values()), list(IncidentEvent.objects.values()))
        response = self.client.get(path + "change/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Audit protection")
        self.assertContains(response, "Created")
        for url, payload in (
            (path + "change/", {"status": "RESOLVED", "resolution_notes": "Bypass"}),
            (path + "delete/", {"post": "yes"}),
            ("/admin/incidents/incident/add/", {}),
        ):
            self.assertEqual(self.client.post(url, payload).status_code, 403)
        self.client.post("/admin/incidents/incident/", {
            "action": "delete_selected", "_selected_action": [self.incident.pk], "post": "yes",
        })
        self.assertEqual(before, (list(Incident.objects.values()), list(IncidentEvent.objects.values())))


class LoginThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.rate = patch.object(LoginRateThrottle, "rate", "5/min", create=True)
        self.rate.start()
        self.addCleanup(self.rate.stop)
        self.addCleanup(cache.clear)

    def test_failed_logins_are_limited_by_ip_and_forwarded_header_cannot_bypass_limit(self):
        for index in range(5):
            response = self.client.post("/api/auth/token/", {
                "username": f"missing-{index}", "password": "wrong",
            }, HTTP_X_FORWARDED_FOR=f"198.51.100.{index}")
            self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/auth/token/", {}, HTTP_X_FORWARDED_FOR="203.0.113.1")
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)
        self.assertEqual(self.client.post("/api/auth/token/", {}, REMOTE_ADDR="192.0.2.1").status_code, 400)

    def test_successful_logins_are_limited_and_access_resumes_after_window(self):
        User.objects.create_user(username="login-limit", password="Login-Test-2026!")
        payload = {"username": "login-limit", "password": "Login-Test-2026!"}
        with patch.object(LoginRateThrottle, "timer", return_value=1000):
            for _ in range(5):
                self.assertEqual(self.client.post("/api/auth/token/", payload).status_code, 200)
            self.assertEqual(self.client.post("/api/auth/token/", payload).status_code, 429)
        with patch.object(LoginRateThrottle, "timer", return_value=1061):
            self.assertEqual(self.client.post("/api/auth/token/", payload).status_code, 200)


class ProductionSettingsTests(SimpleTestCase):
    def run_settings(self, script=None, **overrides):
        env = {**os.environ, "DJANGO_SECRET_KEY": "production-test-only-" + "0123456789abcdef" * 4,
               "DJANGO_SETTINGS_MODULE": "config.production",
               "DJANGO_ALLOWED_HOSTS": "ops.example.com", "REDIS_URL": "redis://localhost:6379/0",
               **overrides}
        # Security and static-file checks do not need PostgreSQL or its native driver.
        setup = (
            "from django.conf import settings\n"
            "settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}\n"
        )
        if script is None:
            script = (
                "import django\ndjango.setup()\n"
                "from django.core.management import call_command\n"
                "call_command('check', deploy=True, fail_level='WARNING')\n"
            )
        return subprocess.run(
            [sys.executable, "-c", setup + script], env=env, capture_output=True, text=True, timeout=30,
        )

    def test_production_passes_deployment_checks(self):
        result = self.run_settings(DJANGO_DEBUG="true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_production_serves_dashboard_and_collected_static_files_over_https(self):
        script = textwrap.dedent("""
            import tempfile
            import django
            from django.core.management import call_command
            from django.contrib.staticfiles.storage import staticfiles_storage
            from django.test import Client, override_settings

            django.setup()
            with tempfile.TemporaryDirectory() as root, override_settings(STATIC_ROOT=root):
                call_command('collectstatic', interactive=False, verbosity=0)
                client = Client(HTTP_HOST='ops.example.com')
                assert client.get('/').status_code == 301
                assert client.get('/', secure=True).status_code == 200
                asset = staticfiles_storage.url('incidents/dashboard.css')
                response = client.get(asset, secure=True)
                try:
                    assert response.status_code == 200
                finally:
                    response.close()
        """)
        result = self.run_settings(script=script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_production_rejects_missing_or_unsafe_configuration(self):
        for override, message in (
            ({"DJANGO_SECRET_KEY": ""}, "DJANGO_SECRET_KEY"),
            ({"DJANGO_SECRET_KEY": "x" * 64}, "DJANGO_SECRET_KEY"),
            ({"DJANGO_ALLOWED_HOSTS": "*"}, "DJANGO_ALLOWED_HOSTS"),
            ({"DJANGO_ALLOWED_HOSTS": ""}, "DJANGO_ALLOWED_HOSTS"),
            ({"REDIS_URL": ""}, "REDIS_URL"),
        ):
            with self.subTest(override=override):
                result = self.run_settings(**override)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
