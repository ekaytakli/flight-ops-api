from django.contrib import admin

from .models import Flight, Incident, IncidentEvent


@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    list_display = ("flight_number", "departure_airport_code", "arrival_airport_code", "scheduled_departure")
    search_fields = ("flight_number", "departure_airport_code", "arrival_airport_code")


class IncidentEventInline(admin.TabularInline):
    model = IncidentEvent
    extra = 0
    can_delete = False
    readonly_fields = ("event_type", "actor", "previous_status", "new_status", "details", "created_at")


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ("id", "flight", "kind", "status", "created_by", "assigned_to", "created_at")
    list_filter = ("kind", "status")
    inlines = [IncidentEventInline]
