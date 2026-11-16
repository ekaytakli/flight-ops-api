# Flight Operations Incident API

Uçuş gecikmelerini ve iptallerini takip etmek için PostgreSQL kullanan bir Django REST Framework API'si. Ekip sorumluları uçuş ve incident kayıtları oluşturur, kayıtları operatörlere atar ve olay geçmişini inceler. Operatörler yalnızca kendilerine atanmış kayıtları görür; bu kayıtlar üzerinde sırasıyla işi başlatıp çözümü tamamlayabilir.

## Özellikler

- Uçuş yönetimi ve role göre erişim sağlayan incident REST uç noktaları.
- Uçuş numarası ve planlanan kalkış zamanı için veritabanı düzeyinde benzersizlik.
- Ayrı işlemlerle yürütülen `OPEN` → `IN_PROGRESS` → `RESOLVED` iş akışı.
- Oluşturma, atama, başlatma ve çözme işlemlerinde aynı veritabanı işlemi içinde tutulan olay geçmişi.
- `Team Leads` ve `Operators` rolleri için Django grupları.
- Token ile kimlik doğrulama, durum/tür filtreleri ve OpenAPI/Swagger dokümantasyonu.
- Türkçe operasyon paneli: hesapla giriş, uçuş/incident oluşturma, operatör seçerek atama, başlatma, çözüm notuyla kapatma ve olay geçmişi.

## Operasyon paneli

Docker Compose ortamını başlattıktan sonra **http://localhost:8000/** adresini açın.
`teamlead` veya `operator` hesabınızın kullanıcı adı ve parolasıyla giriş yapın;
token kopyalamanız gerekmez. Demo hesapları aşağıdaki `create_demo_users` komutuyla oluşturulur.

- **Ekip sorumlusu:** Uçuşlar ekranından bir uçuş oluşturun. Incident kayıtları ekranından uçuşu seçip gecikme veya iptal kaydı açın. Kaydın **Detay** düğmesinden operatörü seçerek atayın, işi başlatın ve çözüm notuyla tamamlayın.
- **Operatör:** Yalnızca size atanmış kayıtlar gösterilir. Detay ekranından işi başlatabilir, çözüm notuyla kapatabilir ve olay geçmişini inceleyebilirsiniz.
- Liste üzerinde arama, durum ve tür filtreleri bulunur. **Yenile** düğmesi güncel kayıtları sunucudan getirir.
- Tarih ve saatler cihazın yerel saat diliminde girilir/gösterilir; API'ye UTC olarak gönderilir.
- Oturum token'ı sekmeye özel `sessionStorage` içinde tutulur. **Çıkış yap**, bu sekmedeki oturumu temizler; sunucudaki API token'ını iptal etmez.

Panel için ek bir Node.js kurulumu veya frontend derleme adımı gerekmez. Django şablonları
ve uygulamanın statik CSS/JavaScript dosyaları kullanılır. Mevcut Docker geliştirme
ortamında statik dosyalar Django tarafından sunulur; üretimde `collectstatic` ve
statik dosya sunumu ayrıca yapılandırılmalıdır.

## Veri modeli

- **Flight** uçuş numarasını, kalkış/varış havalimanlarının IATA kodlarını ve saat dilimi bilgisi içeren planlanan kalkış/varış zamanlarını saklar. `(flight_number, scheduled_departure)` benzersizdir; aynı uçuş numarası başka bir tarihte yeniden kullanılabilir.
- **Incident** bir uçuşa bağlıdır; `DELAY` veya `CANCELLATION` türünü, açıklamayı, oluşturan kullanıcıyı, varsa atanan operatörü, durumu ve çözüm notlarını saklar.
- **IncidentEvent** olay türünü, işlemi yapan kullanıcıyı, zamanı, önceki/yeni durumu ve ayrıntıları saklar. İş akışı servisleri incident satırını kilitler; kayıt güncellemesi ile olay geçmişini tek bir veritabanı işlemi içinde yazar.
- **User/Group** için Django'nun yerleşik kimlik doğrulama altyapısı kullanılır. `Team Leads` ve `Operators` grupları bir veri migration'ı ile oluşturulur.

## Gereksinimler

- Docker Compose içeren Docker Desktop veya Python 3.12+ ve PostgreSQL 16.
- Yerel Python komutlarını kullanmak için `requirements.txt` dosyasındaki paketleri kurun.

## Docker Compose ile çalıştırma

```shell
Copy-Item .env.example .env
```

`.env` içindeki örnek gizli anahtarı ve veritabanı parolasını yerel değerlerle değiştirin; ardından PostgreSQL ve API'yi başlatın:

```shell
docker compose up --build
```

API adresi: `http://localhost:8000/api/`. Compose, PostgreSQL hazır olana kadar bekler, migration'ları uygular ve Django'yu başlatır. Swagger arayüzü `http://localhost:8000/api/docs/`, OpenAPI belgesi ise `http://localhost:8000/api/schema/` adresindedir.

Projede saklanan OpenAPI sözleşmesi [`openapi.yaml`](./openapi.yaml) dosyasındadır.

Yerel örnek senaryo için hesapları oluşturun. Kendi parolalarınızı kullanın; komut parolaları ekrana yazdırmaz:

```shell
docker compose exec api python manage.py create_demo_users --team-lead-password "Lead-Local-2026!" --operator-password "Operator-Local-2026!"
```

Komut, `Team Leads` grubunda `teamlead`, `Operators` grubunda `operator` kullanıcısını oluşturur ve API çağrılarında kullanılacak veritabanı kimliklerini yazdırır. Kullanılabilir parolası olan mevcut hesapların üzerine yazmayı reddeder.

## Kimlik doğrulama

API, Django REST Framework token kimlik doğrulamasını kullanır. Kullanıcı adı ve parola ile token alın:

```shell
curl -X POST http://localhost:8000/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"teamlead","password":"Lead-Local-2026!"}'
```

Sonraki çağrılarda dönen token'ı gönderin:

```shell
curl http://localhost:8000/api/incidents/ \
  -H "Authorization: Token YOUR_TOKEN"
```

## İptal senaryosu

İlk üç çağrıda ekip sorumlusunun token'ını kullanın. Aşağıdaki planlanan zamanlar ISO 8601 biçiminde ve UTC saat dilimindedir.

1. **Uçuş oluşturun**

   ```shell
   curl -X POST http://localhost:8000/api/flights/ \
     -H "Authorization: Token TEAM_LEAD_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"flight_number":"FO401","departure_airport_code":"JFK","arrival_airport_code":"LHR","scheduled_departure":"2026-12-01T10:00:00Z","scheduled_arrival":"2026-12-01T22:00:00Z"}'
   ```

   Dönen uçuş `id` değerini kaydedin.

2. **İptal kaydı açın**

   ```shell
   curl -X POST http://localhost:8000/api/incidents/ \
     -H "Authorization: Token TEAM_LEAD_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"flight":1,"kind":"CANCELLATION","description":"Uçakta teknik arıza var; yolcuların rezervasyonları yenilenmeli."}'
   ```

   Dönen incident `id` değerini kaydedin.

3. **Operatöre atayın**

   ```shell
   curl -X POST http://localhost:8000/api/incidents/1/assign/ \
     -H "Authorization: Token TEAM_LEAD_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"operator_id":OPERATOR_USER_ID}'
   ```

4. Operatör token'ı ile **işi başlatın**:

   ```shell
   curl -X POST http://localhost:8000/api/incidents/1/start/ \
     -H "Authorization: Token OPERATOR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{}'
   ```

5. Operatör token'ı ve zorunlu çözüm notu ile **kaydı çözün**:

   ```shell
   curl -X POST http://localhost:8000/api/incidents/1/resolve/ \
     -H "Authorization: Token OPERATOR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"resolution_notes":"Yedek uçak gönderildi; yolcuların rezervasyonları yenilendi."}'
   ```

6. **Olay geçmişini inceleyin**:

   ```shell
   curl http://localhost:8000/api/incidents/1/events/ \
     -H "Authorization: Token TEAM_LEAD_TOKEN"
   ```

Geçmiş, her geçiş için işlemi yapan kullanıcıyı, olay zamanını, olay türünü ve önceki/sonraki durumu içerir.

## API uç noktaları

| Yöntem | Uç nokta | Erişim |
| --- | --- | --- |
| `POST`, `GET` | `/api/flights/` | Ekip sorumlusu |
| `GET`, `POST` | `/api/incidents/` | Ekip sorumlusu; operatörler yalnızca kendilerine atanmış kayıtları listeler, yalnızca ekip sorumluları kayıt oluşturabilir |
| `GET` | `/api/incidents/{id}/` | Ekip sorumlusu veya atanan operatör |
| `GET` | `/api/incidents/{id}/events/` | Ekip sorumlusu veya atanan operatör |
| `POST` | `/api/incidents/{id}/assign/` | Ekip sorumlusu |
| `POST` | `/api/incidents/{id}/start/` | Ekip sorumlusu veya atanan operatör |
| `POST` | `/api/incidents/{id}/resolve/` | Ekip sorumlusu veya atanan operatör |
| `GET` | `/api/incidents/?status=OPEN&kind=CANCELLATION` | Ekip sorumlusu veya atanan operatör |
| `POST` | `/api/auth/token/` | Önceden token gerekmez; kullanıcı adı ve parola ile token alınır |
| `GET` | `/api/auth/me/` | Ekip sorumlusu veya operatör; mevcut kullanıcı ve rol bilgisi |
| `GET` | `/api/operators/` | Ekip sorumlusu; aktif operatörlerin kimlik ve ad bilgileri |
| `GET` | `/api/schema/`, `/api/docs/` | OpenAPI şeması ve Swagger arayüzü |

Operatörler incident oluşturamaz; liste uç noktası operatörler için salt okunurdur. Incident durumu, ataması ve çözüm notları genel güncelleme çağrılarıyla değiştirilemez.

## Docker olmadan yerel çalıştırma

Sanal ortam oluşturup etkinleştirin, bağımlılıkları kurun ve `.env.example` dosyasından `.env` oluşturun. PostgreSQL'in çalıştığından ve yapılandırılan `POSTGRES_*` değerleriyle erişilebilir olduğundan emin olun.

```shell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py create_demo_users --team-lead-password "Lead-Local-2026!" --operator-password "Operator-Local-2026!"
python manage.py runserver
```

## Testler

Test ayarları, yerel PostgreSQL servisi olmadan çalışabilmek için bellekte bir SQLite veritabanı kullanır. Docker Compose uygulaması ve GitHub Actions ise PostgreSQL kullanır.

```shell
python manage.py test --settings=config.test_settings
python manage.py check --settings=config.test_settings
```

Çalışan Compose ortamındaki PostgreSQL veritabanı üzerinde doğrulama yapın:

```shell
docker compose exec api python manage.py migrate --noinput
docker compose exec api python manage.py check
docker compose exec api python manage.py makemigrations --check --dry-run
docker compose exec api python manage.py test
docker compose exec api python manage.py spectacular --validate --fail-on-warn --file /tmp/openapi.yaml
```

Testler; token ile doğrulanan iptal akışını, role göre erişimi, reddedilen isteklerde tüm incident ve olay alanlarının korunmasını ve olay geçmişi yazılamadığında işlemin geri alınmasını kapsar. SQLite, PostgreSQL'in satır kilitleme davranışını doğrulamaz; PostgreSQL üzerinde doğrulama için Compose veya CI testlerini kullanın.

API şema açıklamalarını değiştirdikten sonra projedeki sözleşmeyi yeniden üretin:

```shell
python manage.py spectacular --validate --fail-on-warn --file openapi.yaml
```
