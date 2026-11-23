from datetime import datetime, time, timedelta, timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from incidents.models import Flight, Incident
from incidents.roles import OPERATOR_GROUP, TEAM_LEAD_GROUP
from incidents.services import assign_incident, create_incident, resolve_incident, start_incident
from .create_demo_flights import demo_flight_data


# Fictional operational reports; these are not maintenance instructions or live alerts.
SCENARIOS = (
    ("DELAY", "HIGH", "Hidrolik sistem basınç uyarısı", "Uçuşa hazırlık kontrolünde hidrolik basınç uyarısı bildirildi; teknik değerlendirme bekleniyor."),
    ("CANCELLATION", "CRITICAL", "Motor parametrelerinde anormallik", "Planlanan sefere ayrılan uçakta motor parametreleri için teknik uygunsuzluk bildirildi; alternatif uçak bulunamadığından iptal süreci açıldı."),
    ("DELAY", "HIGH", "Fren sistemi bakım bulgusu", "Yer kontrolünde fren sistemi için bakım gereksinimi raporlandı; kalkış planı teknik ekip değerlendirmesine alındı."),
    ("DELAY", "NORMAL", "APU başlatma sorunu", "Uçuş hazırlığında yardımcı güç ünitesi başlatılamadı; yer destek ve bakım koordinasyonu gerekiyor."),
    ("DELAY", "HIGH", "Elektrik jeneratörü uyarısı", "Elektrik sistemi kontrolünde jeneratör uyarısı raporlandı; uçuşa hazırlık durumu teknik ekibe soruldu."),
    ("CANCELLATION", "CRITICAL", "Uçuş kontrol sistemi uyarısı", "Planlanan uçakta uçuş kontrol sistemi uyarısı nedeniyle teknik uygunluk alınamadı; yedek uçak bulunamadığından sefer iptal sürecinde."),
    ("DELAY", "NORMAL", "Kabin iklimlendirme sorunu", "Kabin iklimlendirme sisteminin kontrolü gerekiyor; yolcu alımının başlatılması teknik değerlendirmeyi bekliyor."),
    ("DELAY", "HIGH", "Kargo kapısı kilit göstergesi", "Yer kontrolünde kargo kapısı kilit göstergesinde tutarsızlık raporlandı; teknik inceleme talep edildi."),
    ("DELAY", "NORMAL", "Telsiz iletişim sorunu", "Uçuş hazırlığında telsiz iletişimiyle ilgili teknik bulgu bildirildi; bakım ekibi ile operasyon planı koordine ediliyor."),
    ("CANCELLATION", "HIGH", "Hava radarı teknik uygunsuzluğu", "Hava radarı için teknik uygunluk sağlanamadı; alternatif uçak olmaması nedeniyle iptal ve yolcu aktarım süreci açıldı."),
    ("DELAY", "HIGH", "Lastik basınç uyarısı", "Yer kontrolünde lastik basınç uyarısı alındı; bakım değerlendirmesi için kalkış planında bekleme var."),
    ("DELAY", "NORMAL", "Yakıt miktar göstergesi tutarsızlığı", "Yakıt miktar göstergeleri arasında tutarsızlık raporlandı; teknik doğrulama tamamlanana kadar operasyon koordinasyonu sürüyor."),
    ("DELAY", "HIGH", "Ön cam ısıtma sistemi uyarısı", "Uçuş öncesi kontrolde ön cam ısıtma sistemi uyarısı bildirildi; teknik ekipten durum bilgisi bekleniyor."),
    ("DELAY", "NORMAL", "İniş takımı konum sensörü bildirimi", "İniş takımı konum göstergesi için teknik kontrol talebi açıldı; tahmini hazır olma zamanı takip ediliyor."),
    ("CANCELLATION", "CRITICAL", "Kabin basınçlandırma sistemi bulgusu", "Kabin basınçlandırma sistemi için bakım süresi kalkış planını aşıyor; alternatif uçak bulunamadığından iptal koordinasyonu başlatıldı."),
    ("DELAY", "LOW", "Kabin aydınlatması arızası", "Kabin aydınlatma ünitesindeki arıza bakım ekibine iletildi; operasyonun yeni hazır olma saati bekleniyor."),
    ("DELAY", "NORMAL", "Seyrüsefer ekranı arızası", "Kokpit seyrüsefer ekranı için teknik bulgu bildirildi; uygunluk ve kalkış planı güncellemesi bekleniyor."),
    ("DELAY", "HIGH", "Oksijen sistemi teknik bildirimi", "Uçuş hazırlığında oksijen sistemiyle ilgili teknik bildirim alındı; bakım değerlendirmesi talep edildi."),
    ("DELAY", "LOW", "Mutfak ünitesi elektrik arızası", "Kabin mutfak ünitesindeki elektrik arızası teknik ekibe bildirildi; kabin hazırlığı koordine ediliyor."),
    ("DELAY", "NORMAL", "Su sistemi sızıntı bildirimi", "Kabin su sistemi için sızıntı bildirimi alındı; bakım ekibi ve yer hizmetleri hazırlık planını değerlendiriyor."),
)


class Command(BaseCommand):
    help = "Uçuş sayısını hedefe tamamlar ve istenen oranda çeşitli sentetik teknik incident oluşturur."

    def add_arguments(self, parser):
        parser.add_argument("--flight-count", type=int, default=200)
        parser.add_argument("--incident-percent", type=int, default=10)
        parser.add_argument("--team-lead", default="teamlead")
        parser.add_argument("--operator", default="operator")

    @transaction.atomic
    def handle(self, *args, **options):
        target = options["flight_count"]
        percent = options["incident_percent"]
        if not 1 <= target <= 10000 or not 0 <= percent <= 100:
            raise CommandError("Uçuş sayısı 1–10000, incident yüzdesi 0–100 arasında olmalıdır.")
        total = Flight.objects.count()
        affected = Incident.objects.values("flight_id").distinct().count()
        if total > target or affected > target * percent // 100:
            raise CommandError("Mevcut veriler hedefi aşıyor; kayıt silinmedi. Daha yüksek bir hedef seçin.")
        users = get_user_model().objects.filter(is_active=True)
        lead = users.filter(username=options["team_lead"], groups__name=TEAM_LEAD_GROUP).first()
        operator = users.filter(username=options["operator"], groups__name=OPERATOR_GROUP).first()
        if lead is None or operator is None:
            raise CommandError("Aktif ekip sorumlusu ve operatör hesapları gereklidir.")

        first_demo = Flight.objects.filter(flight_number="DM1001").order_by("scheduled_departure").first()
        day = first_demo.scheduled_departure.date() if first_demo else timezone.localdate() + timedelta(days=1)
        start = datetime.combine(day, time(6), tzinfo=datetime_timezone.utc)
        added = 0
        for index in range(10000):
            if total + added >= target:
                break
            data = demo_flight_data(index, start)
            _, created = Flight.objects.get_or_create(
                flight_number=data.pop("flight_number"), scheduled_departure=data.pop("scheduled_departure"),
                defaults=data,
            )
            added += created

        incident_target = target * percent // 100
        needed = incident_target - affected
        counts = dict(Incident.objects.values("status").annotate(total=Count("pk")).values_list("status", "total"))
        quotas = {"OPEN": incident_target * 4 // 10, "IN_PROGRESS": incident_target * 3 // 10}
        quotas["RESOLVED"] = incident_target - sum(quotas.values())
        statuses = [status for status, quota in quotas.items() for _ in range(max(0, quota - counts.get(status, 0)))]
        candidates = list(Flight.objects.filter(incidents__isnull=True).order_by("scheduled_departure", "pk")[:needed])
        now = timezone.now()
        for index, flight in enumerate(candidates):
            kind, priority, title, description = SCENARIOS[index % len(SCENARIOS)]
            incident = create_incident(actor=lead, validated_data={
                "flight": flight, "kind": kind, "priority": priority,
                "description": f"{title}: {description}",
            })
            status = statuses[index] if index < len(statuses) else "OPEN"
            # Some open records await triage; others are already assigned.
            if status != "OPEN" or index % 2:
                assign_incident(incident_id=incident.pk, actor=lead, operator=operator)
            if status in ("IN_PROGRESS", "RESOLVED"):
                start_incident(incident_id=incident.pk, actor=operator)
            if status == "RESOLVED":
                notes = (
                    "İptal operasyonu tamamlandı; yolcuların alternatif seferlere aktarımı koordine edildi. "
                    "Uçağın teknik takibi yetkili bakım ekibine devredildi."
                    if kind == "CANCELLATION" else
                    "Yetkili bakım ekibinden teknik uygunluk bildirimi alındı; yeni kalkış planı "
                    "yer hizmetleri ve uçuş ekibiyle paylaşıldı, operasyon kaydı kapatıldı."
                )
                resolve_incident(incident_id=incident.pk, actor=operator, resolution_notes=notes)
            # Only newly generated demo history is dated back, preserving chronological audit events.
            created_at = now - timedelta(minutes=35 + index * 53 + (index * index * 17) % 241)
            events = list(incident.events.order_by("created_at", "pk"))
            last_action = created_at
            for step, event in enumerate(events):
                if step:
                    last_action += timedelta(minutes=3 + (index * 13 + step * 7) % 64)
                incident.events.filter(pk=event.pk).update(created_at=last_action)
            Incident.objects.filter(pk=incident.pk).update(created_at=created_at, updated_at=last_action)

        summary = dict(Incident.objects.values("status").annotate(total=Count("pk")).values_list("status", "total"))
        self.stdout.write(self.style.SUCCESS(
            f"{added} uçuş ve {len(candidates)} teknik incident eklendi. "
            f"Toplam: {Flight.objects.count()} uçuş, "
            f"{Incident.objects.values('flight_id').distinct().count()} incident bulunan uçuş. Durumlar: {summary}"
        ))
