"""One-time refresh of the original local demo, with strict dataset guards."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from incidents.models import Flight, Incident, IncidentEvent
from incidents.roles import OPERATOR_GROUP, TEAM_LEAD_GROUP
from incidents.services import assign_incident, create_incident, resolve_incident, start_incident
from .create_demo_operations import SCENARIOS


class Command(BaseCommand):
    help = "İlk üç test arızasını değiştirir, demo sürelerini ve beş operatörün iş dağılımını düzenler."

    @transaction.atomic
    def handle(self, *args, **options):
        legacy = list(Incident.objects.filter(pk__in=[1, 2, 3]).order_by('pk'))
        replacement_numbers = ['DM1018', 'DM1019', 'DM1020']
        if not legacy and Incident.objects.filter(flight__flight_number__in=replacement_numbers).count() == 3:
            self.stdout.write('Demo düzenlemesi zaten uygulanmış; veriler değiştirilmedi.')
            return
        expected = ['Technical issue; rebooking required.',
                    'Operasyon paneli do?rulamas?: teknik ar?za nedeniyle iptal.',
                    'Operasyon paneli doğrulaması: teknik arıza nedeniyle iptal.']
        if [item.description for item in legacy] != expected:
            raise CommandError('İlk üç kayıt beklenen eski test kayıtları değil; değişiklik yapılmadı.')
        demo = list(Incident.objects.exclude(pk__in=[1, 2, 3]).select_related('flight').order_by('-created_at', '-pk'))
        if len(demo) != 17 or any(
            not item.flight.flight_number.startswith('DM') or
            item.description.split(':', 1)[0] not in {row[2] for row in SCENARIOS}
            for item in demo
        ):
            raise CommandError('Beklenen 17 teknik demo kaydı bulunamadı; değişiklik yapılmadı.')
        flights = []
        for number in replacement_numbers:
            candidates = Flight.objects.filter(flight_number=number, incidents__isnull=True)
            if candidates.count() != 1:
                raise CommandError(f'{number} için arızasız tek bir demo uçuşu gerekli.')
            flights.append(candidates.get())
        users = get_user_model().objects
        lead = users.get(username='teamlead', groups__name=TEAM_LEAD_GROUP, is_active=True)
        original = users.get(username='operator', groups__name=OPERATOR_GROUP, is_active=True)
        group = Group.objects.get(name=OPERATOR_GROUP)
        names = ['operator', 'operator2', 'operator3', 'operator4', 'operator5']
        if users.filter(groups=group).exclude(username__in=names).exists():
            raise CommandError('Beklenmeyen operatör hesapları var; değişiklik yapılmadı.')
        operators = [original]
        for name in names[1:]:
            user, created = users.get_or_create(username=name, defaults={'password': original.password, 'is_active': True})
            if not created and (not user.is_active or not user.groups.filter(pk=group.pk).exists()):
                raise CommandError(f'{name} hesabı demo operatörü olarak kullanılamıyor.')
            user.groups.add(group)
            operators.append(user)

        Incident.objects.filter(pk__in=[1, 2, 3]).delete()
        # New records keep ordinary database identities; their dates place them after the older demo entries.
        for index, flight in enumerate(flights):
            kind, priority, title, description = SCENARIOS[17 + index]
            item = create_incident(actor=lead, validated_data={
                'flight': flight, 'kind': kind, 'priority': priority,
                'description': f'{title}: {description}',
            })
            operator = operators[(17 + index) % 5]
            assign_incident(incident_id=item.pk, actor=lead, operator=operator)
            start_incident(incident_id=item.pk, actor=operator)
            resolve_incident(incident_id=item.pk, actor=operator, resolution_notes=(
                'Yetkili bakım ekibinden teknik uygunluk bildirimi alındı; '
                'uçuş ve yer hizmetleri ekiplerine güncel operasyon planı iletildi.'
            ))
            item.refresh_from_db()
            demo.append(item)

        ages = [7, 23, 48, 92, 155, 236, 347, 491, 680, 845,
                1048, 1290, 1550, 1841, 2200, 2660, 3180, 3790, 4460, 5200]
        now = timezone.now()
        assigned_index = 0
        for index, item in enumerate(demo):
            selected = []
            if item.assigned_to_id:
                selected = [operators[assigned_index % 5]]
                if assigned_index % 4 == 0:
                    selected.append(operators[(assigned_index + 1) % 5])
                assigned_index += 1
            item.assigned_to = selected[0] if selected else None
            item.save(update_fields=['assigned_to'])
            item.supporting_operators.set(selected[1:])
            created_at = now - timedelta(minutes=ages[index])
            wait = 9 + (index * 17) % 103
            last_action = created_at
            for event in item.events.order_by('created_at', 'pk'):
                if event.event_type == IncidentEvent.Type.ASSIGNED:
                    last_action = created_at + timedelta(minutes=min(ages[index] // 3, max(1, wait // 3)))
                    event.details = {'previous_operator': None, 'previous_operators': [],
                                     'assigned_operator': selected[0].username,
                                     'assigned_operators': [user.username for user in selected]}
                elif event.event_type == IncidentEvent.Type.STARTED:
                    last_action = created_at + timedelta(minutes=wait)
                    event.actor = selected[-1]
                elif event.event_type == IncidentEvent.Type.RESOLVED:
                    last_action = created_at + timedelta(minutes=wait + 31 + (index * 29) % 173)
                    event.actor = selected[0]
                event.created_at = last_action
                event.save(update_fields=['created_at', 'details', 'actor'])
            Incident.objects.filter(pk=item.pk).update(created_at=created_at, updated_at=last_action)
        self.stdout.write(self.style.SUCCESS('3 test kaydı silindi, 3 teknik arıza eklendi. 20 arıza, 5 operatör; süreler ve ortak atamalar düzenlendi.'))
