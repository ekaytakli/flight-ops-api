from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from incidents.roles import OPERATOR_GROUP, TEAM_LEAD_GROUP

User = get_user_model()


class Command(BaseCommand):
    help = "Yerel örnek senaryo için bir ekip sorumlusu ve bir operatör hesabı oluşturur."

    def add_arguments(self, parser):
        parser.add_argument("--team-lead-password", required=True)
        parser.add_argument("--operator-password", required=True)

    def handle(self, *args, **options):
        from django.contrib.auth.models import Group

        passwords = {
            "teamlead": options["team_lead_password"],
            "operator": options["operator_password"],
        }
        for username, group_name in (
            ("teamlead", TEAM_LEAD_GROUP),
            ("operator", OPERATOR_GROUP),
        ):
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"is_active": True},
            )
            if not created and user.has_usable_password():
                raise CommandError(
                    f"User {username!r} already exists. Choose a new username or manage it manually."
                )
            user.set_password(passwords[username])
            user.save()
            user.groups.add(Group.objects.get(name=group_name))
            self.stdout.write(
                f"{'Created' if created else 'Updated'} {group_name} user: "
                f"{username} (id={user.pk})"
            )
