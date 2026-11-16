from rest_framework.filters import OrderingFilter


class StableOrderingFilter(OrderingFilter):
    def get_ordering(self, request, queryset, view):
        ordering = list(super().get_ordering(request, queryset, view) or ["pk"])
        if not any(field.lstrip("-") in ("id", "pk") for field in ordering):
            ordering.append("pk")
        return ordering


class IncidentOrderingFilter(StableOrderingFilter):
    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        fields = [field.replace("priority", "priority_rank") for field in ordering]
        return queryset.order_by(*fields)
