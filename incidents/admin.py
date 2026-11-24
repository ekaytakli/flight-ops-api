from django.contrib import admin

from .models import Flight, FlightAuditEvent, Incident, IncidentEvent


@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    list_display = ("flight_number", "departure_airport_code", "arrival_airport_code", "scheduled_departure")
    search_fields = ("flight_number", "departure_airport_code", "arrival_airport_code")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FlightAuditEvent)
class FlightAuditEventAdmin(admin.ModelAdmin):
    list_display = ("flight_identifier", "event_type", "actor", "created_at")
    list_filter = ("event_type",)
    search_fields = ("=flight_identifier", "actor__username")
    readonly_fields = tuple(field.name for field in FlightAuditEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class IncidentEventInline(admin.TabularInline):
    model = IncidentEvent
    extra = 0
    can_delete = False
    readonly_fields = ("event_type", "actor", "previous_status", "new_status", "details", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ("id", "flight", "kind", "status", "created_by", "assigned_to", "created_at")
    list_filter = ("kind", "status")
    inlines = [IncidentEventInline]
    readonly_fields = tuple(field.name for field in Incident._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
