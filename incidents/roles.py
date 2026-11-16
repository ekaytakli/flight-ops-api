TEAM_LEAD_GROUP = "Team Leads"
OPERATOR_GROUP = "Operators"


def is_team_lead(user):
    return user.is_authenticated and user.groups.filter(name=TEAM_LEAD_GROUP).exists()


def is_operator(user):
    return user.is_authenticated and user.groups.filter(name=OPERATOR_GROUP).exists()
