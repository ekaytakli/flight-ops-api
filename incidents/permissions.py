from rest_framework.permissions import BasePermission

from .roles import is_operator, is_team_lead


class IsTeamLead(BasePermission):
    def has_permission(self, request, view):
        return is_team_lead(request.user)


class IsTeamLeadOrOperator(BasePermission):
    def has_permission(self, request, view):
        return is_team_lead(request.user) or is_operator(request.user)


class IsTeamLeadOrAssignedOperator(BasePermission):
    def has_object_permission(self, request, view, obj):
        return is_team_lead(request.user) or (
            is_operator(request.user) and obj.has_operator(request.user)
        )
