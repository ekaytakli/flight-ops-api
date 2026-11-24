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
- Düşük, normal, yüksek ve kritik incident öncelikleri; öncelik değişikliklerinin olay geçmişinde tutulması.
- Sunucu tarafında arama, sayfalama ve sıralama; bekleme süresi ve son işlem zamanı.
- Panelden uçuş düzenleme, parola değiştirme ve sunucuda token iptal eden çıkış işlemi.

## Operasyon paneli

Docker Compose ortamını başlattıktan sonra **http://localhost:8000/** adresini açın.
`teamlead` veya `operator` hesabınızın kullanıcı adı ve parolasıyla giriş yapın;
token kopyalamanız gerekmez. Demo hesapları aşağıdaki `create_demo_users` komutuyla oluşturulur.

- **Ekip sorumlusu:** Uçuşlar ekranından bir uçuş oluşturun. Incident kayıtları ekranından uçuşu seçip gecikme veya iptal kaydı açın. Kaydın **Detay** düğmesinden operatörü seçerek atayın, işi başlatın ve çözüm notuyla tamamlayın.
- **Operatör:** Yalnızca size atanmış kayıtlar gösterilir. Detay ekranından işi başlatabilir, çözüm notuyla kapatabilir ve olay geçmişini inceleyebilirsiniz.
- Liste üzerinde arama, durum, tür ve öncelik filtreleri bulunur. Önceliğe, kayıt/son işlem zamanına veya uçuşa göre sıralama yapılabilir. **Yenile** düğmesi güncel kayıtları sunucudan getirir.
- Listeler 20, 50 veya 100 kayıtlık sayfalarla gösterilir. Özet kartları filtrelerden ve sayfadan bağımsız olarak kullanıcının erişebildiği tüm incident kayıtlarını sayar.
- Uçuşlar ekranındaki **Düzenle** düğmesi uçuş bilgilerini günceller. Incident açarken uçuş araması ilk 20 eşleşmeyi getirir; eski uçuşlar numara veya havalimanıyla aranabilir.
- Incident önceliği oluşturma sırasında seçilir; ekip sorumlusu açık veya işlemdeki kaydın detayından değiştirebilir. Çözülmüş kaydın önceliği değiştirilemez. Aynı önceliği yeniden kaydetmek ek olay oluşturmaz.
- Bekleme süresi açılıştan ilk işe başlama anına kadardır; açık kayıtlarda artar, iş başlatıldığında sabitlenir. İşlem süresi ilk `STARTED` olayından şu ana (çözülmüş kayıtta ilk `RESOLVED` olayına) kadar geçen süredir. Toplam süre açılıştan şu ana veya çözüm anına kadardır. Listede mevcut aşamanın süresi ve toplam süre, detayda üç süre ile açılış/başlama/çözüm tarihleri gösterilir. Devam eden sayaçlar sayfa yenilenmeden ilerler; çözülmüş kayıtların süreleri sabittir. Son işlem zamanı `updated_at`, süre başlangıcı olarak kullanılmaz.
- Tarih ve saatler cihazın yerel saat diliminde girilir/gösterilir; API'ye UTC olarak gönderilir.
- Oturum token'ı sekmeye özel `sessionStorage` içinde tutulur. **Çıkış yap**, sunucudaki token'ı iptal edip yerel oturumu temizler. DRF kullanıcı başına tek token kullandığından aynı token ile açık diğer sekmeler de yeniden giriş yapmalıdır. Ağ hatasında sunucudaki iptal doğrulanamadığı için panel oturumu açık tutar ve hata gösterir.
- Üst menüdeki **Parolamı değiştir**, mevcut parolayı ve Django parola kurallarını doğrular. Başarılı değişiklik parolayı güncelleyip kullanıcının token'ını aynı veritabanı işlemi içinde iptal eder. Yeni parolayla tekrar giriş gerekir.

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

## Örnek uçuş verileri

Yerel demo ortamında operatörler `operator`, `operator2`, `operator3`, `operator4` ve
`operator5` hesaplarıdır. Eklenen dört hesap, oluşturuldukları sırada `operator`
hesabının parolasını kullanır. Açık bir arızanın detayındaki operatör listesinden
Ctrl / ⌘ ile en fazla iki kişi birlikte seçilebilir. İki operatör de kaydı görür,
başlatabilir ve çözebilir. API atama isteği `{"operator_ids": [2, 3]}` kabul eder;
eski `{"operator_id": 2}` biçimi tek operatör atamaya devam eder.
Yanıttaki `assigned_operators` tüm atanan kullanıcı adlarını içerir;
`assigned_to` ilk operatörü içererek mevcut istemcilerle uyumu korur.

İlk üç eski test arızasını değiştirmek için kullanılan tek seferlik
`refresh_demo_operations` komutu, yalnızca beklenen başlangıç demo verisini kabul
eder; üç test arızasını silip üç teknik senaryo ekler, süreleri çeşitlendirir ve
beş operatör arasında ortak atamalar yapar. Toplam uçuş ve arıza sayıları korunur;
tekrar çalıştırıldığında zamanları veya kayıtları yeniden değiştirmez.

20 havalimanını ve 100 farklı güzergâhı kapsayan 100 sentetik uçuş eklemek için:

```shell
docker compose exec api python manage.py create_demo_flights
```

Komut mevcut uçuşları değiştirmez. Başlangıç tarihi varsayılan olarak yarındır;
uçuşlar yaklaşık dokuz güne yayılır. Bunlar gerçek sefer veya canlı arıza verileri değildir.
Aynı başlangıç tarihi ve sayıyla tekrar çalıştırmak mükerrer kayıt oluşturmaz:

```shell
docker compose exec api python manage.py create_demo_flights --count 100 --start-date 2026-12-01
```

### Teknik arıza senaryolarıyla 200 uçuş

Mevcut uçuşları 200'e tamamlamak ve uçuşların %10'unda teknik incident bulunmasını
sağlamak için (önce demo kullanıcıları oluşturun):

```shell
docker compose exec api python manage.py create_demo_operations
```

Komut mevcut uçuşları, incident'ları ve olay geçmişini korur. Mevcut 103 uçuş ve
3 çözülmüş incident bulunan örnekte 97 uçuş ve 17 incident ekler: toplam 200 uçuş,
20 incident bulunan uçuş; 8 açık, 6 işlemde, 6 çözülmüş kayıt. Açık kayıtların bir
kısmı atama bekler, bir kısmı operatöre atanmıştır. Gecikme ve iptaller; motor,
hidrolik, fren, elektrik, APU, kabin sistemleri gibi farklı teknik bildirimler ve
öncelikler içerir. Çözülmüş kayıtlarda operasyon çözüm notu bulunur; iptal
operasyonunun kapanması, uçağın bakımının tamamlandığı anlamına gelmez.

Atama, başlatma ve kapatma normal iş akışı servisleriyle yapılır. Yalnızca yeni demo
kayıtlarının zamanları tutarlı bir geçmiş oluşturacak şekilde ayarlanır. Aynı hedefle
tekrar çalıştırmak kayıt eklemez veya mevcut durumları sıfırlamaz. Mevcut veri hedefi
aşıyorsa komut veri silmek yerine durur. `--flight-count` ve `--incident-percent`
ile hedef değiştirilebilir. Bu veriler simülasyondur; %10 oranı gerçek havacılık
arıza istatistiği veya otomatik arıza tespiti iddiası değildir.

## Kimlik doğrulama

API, Django REST Framework token kimlik doğrulamasını kullanır. Kullanıcı adı ve parola ile token alın:

Token alma uç noktası IP başına dakikada 5 istekle sınırlıdır; başarılı ve başarısız
denemeler bu sınıra dahildir. Sınır aşılınca `429` ve `Retry-After` başlığı döner.
Geliştirmede sayaç süreç belleğinde, üretimde ortak Redis önbelleğinde tutulur.
DRF hız sınırlaması eşzamanlı isteklerde kesin bir üst sınır sağlamaz; internete açık
dağıtımlarda proxy katmanında da giriş uç noktasına istek sınırı uygulayın.

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
| `GET`, `PUT`, `PATCH`, `DELETE` | `/api/flights/{id}/` | Ekip sorumlusu; incident bağlı uçuşlar silinemez (`409`) |
| `GET`, `POST` | `/api/incidents/` | Ekip sorumlusu; operatörler yalnızca kendilerine atanmış kayıtları listeler, yalnızca ekip sorumluları kayıt oluşturabilir |
| `GET` | `/api/incidents/{id}/` | Ekip sorumlusu veya atanan operatör |
| `GET` | `/api/incidents/{id}/events/` | Ekip sorumlusu veya atanan operatör |
| `POST` | `/api/incidents/{id}/assign/` | Ekip sorumlusu |
| `POST` | `/api/incidents/{id}/start/` | Ekip sorumlusu veya atanan operatör |
| `POST` | `/api/incidents/{id}/resolve/` | Ekip sorumlusu veya atanan operatör |
| `POST` | `/api/incidents/{id}/priority/` | Ekip sorumlusu; `{"priority":"HIGH"}` ile öncelik değişikliği |
| `GET` | `/api/incidents/summary/` | Ekip sorumlusu veya operatör; rol kapsamındaki tüm kayıtların durum sayıları |
| `GET` | `/api/incidents/?status=OPEN&kind=CANCELLATION` | Ekip sorumlusu veya atanan operatör |
| `POST` | `/api/auth/token/` | Önceden token gerekmez; kullanıcı adı ve parola ile token alınır |
| `GET` | `/api/auth/me/` | Ekip sorumlusu veya operatör; mevcut kullanıcı ve rol bilgisi |
| `POST` | `/api/auth/logout/` | Token ile giriş yapmış kullanıcı; token iptali, başarılı yanıt `204` |
| `POST` | `/api/auth/password/` | Token ile giriş yapmış kullanıcı; `old_password`, `new_password` alanları, başarılı yanıt `204` |
| `GET` | `/api/operators/` | Ekip sorumlusu; aktif operatörlerin kimlik ve ad bilgileri |
| `GET` | `/api/schema/`, `/api/docs/` | OpenAPI şeması ve Swagger arayüzü |

Operatörler incident oluşturamaz; liste uç noktası operatörler için salt okunurdur. Incident durumu, ataması ve çözüm notları genel güncelleme çağrılarıyla değiştirilemez.

Uçuş düzenleme için `PATCH /api/flights/{id}/` veya `PUT /api/flights/{id}/` kullanılır;
yalnızca ekip sorumluları yetkilidir. Mevcut zaman, havalimanı ve benzersizlik doğrulamaları uygulanır.

`DELETE /api/flights/{id}/`, incident kaydı olmayan uçuşları siler ve `204` döndürür.
Herhangi bir durumda incident kaydı bağlıysa `409` ve
`{"detail":"Flights with incidents cannot be deleted."}` döner; uçuş, incident ve olay
geçmişi korunur. Bulunamayan uçuş için `404` döner.

Açık bir incident aynı operatöre tekrar atandığında istek başarılı olur; ek `ASSIGNED`
olayı yazılmaz ve `updated_at` değişmez. İşlemdeki veya çözülmüş kayıtlarda atama
isteği, operatör aynı olsa da reddedilir.

### Sayfalama ve sıralama

Uçuş ve incident listeleri artık düz dizi yerine `count`, `next`, `previous`, `results`
alanlarını döndürür. API istemcileri kayıtları `results` içinden okumalıdır.
Varsayılan sayfa boyutu 20, en yüksek değer 100'dür. Operatör listesi ve olay geçmişi düz dizi olarak kalır.

```text
/api/incidents/?page=1&page_size=20&ordering=-priority&priority=HIGH&status=OPEN&search=TK
/api/flights/?page=1&page_size=20&ordering=scheduled_departure&search=IST
```

Incident sıralama alanları: `created_at`, `updated_at`, `priority`, `flight__flight_number`, `id`.
Uçuş sıralama alanları: `scheduled_departure`, `scheduled_arrival`, `flight_number`, `id`.
Başına `-` eklemek azalan sıralama sağlar. Öncelik sırası `LOW < NORMAL < HIGH < CRITICAL` şeklindedir;
aynı değere sahip kayıtlarda kimlik alanı kararlı bir sıralama sağlar. En uzun bekleyen açık kayıtları
görmek için `status=OPEN&ordering=created_at` kullanın.

Mevcut incident kayıtları `0003` migration'ı ile `NORMAL` öncelik kazanır. `waiting_seconds`,
`processing_seconds`, `total_seconds`, `started_at` ve `resolved_at` salt okunurdur.
Süreler mevcut olay geçmişinden hesaplanır; veri migration'ı gerekmez ve eski kayıtlar
da aynı hesaplamayı kullanır. Başlama/çözüm geçmişi eksikse bu geçmişe bağlı süreler
`null` döner ve panelde `—` gösterilir. Açık kayıtta işlem süresi `0`, başlama ve
çözüm tarihleri `null` olur.

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

## Üretim dağıtımı

Docker Compose dosyası yerel geliştirme içindir ve `runserver` kullanmaya devam eder.
Docker imajının varsayılan komutu statik dosyaları toplar, ardından iki worker ile Gunicorn başlatır ve
`config.production` ayarlarını kullanır. Bu ayarlar `DEBUG=False` uygular;
50 karakterden kısa/zayıf gizli anahtar, boş veya `*` host listesi ve eksik
`REDIS_URL` ile uygulama başlamaz.

Üretim ortamında `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `POSTGRES_*` ve
`REDIS_URL` değerlerini dağıtımın gizli ortam değişkenlerinden sağlayın. PostgreSQL
ve Redis'i yalnızca uygulamanın erişebileceği ağda tutun. Ortak Redis tüm Gunicorn
worker'larının giriş denemelerini aynı sayaç üzerinden sınırlamasını sağlar.

HTTPS sonlandıran güvenilir proxy arkasında `DJANGO_TRUST_PROXY=true` ve gerçek
proxy sayısına uygun `DJANGO_NUM_PROXIES` kullanın. Proxy gelen istemci
`X-Forwarded-Proto` ve `X-Forwarded-For` başlıklarını temizleyip kendisi yazmalıdır.
Varsayılan ayarlar forwarded başlıklara güvenmez. Üretim HTTPS'e yönlendirir,
güvenli oturum/CSRF çerezleri ve alt alan adlarını kapsayan bir yıllık HSTS uygular.
Uygulama alan adının alt alan adları da HTTPS kullanmalıdır. `preload` işareti
açıktır; bu işaret alan adını tarayıcıların preload listesine kendiliğinden eklemez.

İmajı oluşturduktan sonra aynı imajla dağıtım öncesi tek seferlik görevler olarak çalıştırın
(komutlara üretim ortam değişkenlerini `--env-file` ile verin):

```shell
docker build -t flight-ops-api .
docker run --rm --env-file .env.production flight-ops-api python manage.py check --deploy --fail-level WARNING --settings=config.production
docker run --rm --env-file .env.production flight-ops-api python manage.py migrate --noinput --settings=config.production
```

Statik dosyalar her container'ın başlangıcında `collectstatic` ile hazırlanır.
Uygulamayı HTTPS proxy'nin erişebileceği şekilde başlatın:

```shell
docker run --env-file .env.production -p 127.0.0.1:8000:8000 flight-ops-api
```

WhiteNoise, `STATIC_ROOT` altına toplanan sürümlenmiş ve sıkıştırılmış statik dosyaları
sunar. `.env.production` dosyası Git'e eklenmez. Django admin'de incident ve olay
geçmişi yalnızca görüntülenebilir; oluşturma, atama, durum/öncelik değişikliği için
operasyon panelini veya API'yi kullanın. Incident silme ve toplu silme kapalıdır.

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

PostgreSQL eşzamanlılık testleri iki ayrı bağlantının aynı kaydı başlatmasını/çözmesini,
yalnızca tek geçiş ve olay yazılmasını ve satır kilidi beklerken değişen operatör atamasının
kilit alındıktan sonra yeniden kontrol edilmesini sınar. Bu üç test SQLite üzerinde atlanır.
Parola, sunucuda çıkış, öncelik/audit atomikliği, bekleme süresi, sayfalama/sıralama ve uçuş
düzenleme testleri her iki veritabanında da çalışır.

API şema açıklamalarını değiştirdikten sonra projedeki sözleşmeyi yeniden üretin:

```shell
python manage.py spectacular --validate --fail-on-warn --file openapi.yaml
```
