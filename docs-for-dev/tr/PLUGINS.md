# Üçüncü taraf eklenti geliştirme

[El kitabı](README.md) · [Araçlar ve yetenekler](TOOLS_AND_CAPABILITIES.md) · [Okuma uzantıları](READING_EXTENSIONS.md)

Resmî [modül wheel'leri](MODULES.md) DeepTutor'ın yorumlayıcısını ve sürümünü
paylaşır. Üçüncü taraf eklentilerin ise ayrı bir manifest, onay ve yaşam döngüsü
sözleşmesi vardır. Çalıştırılabilir [Learning Echo örneğiyle](examples/learning_echo/README.md)
başlayın; bu örnek, harici Python bağımlılığı olmadan bir araç, yetenek, HTTP
route'u ve statik sayfa bildirir.

## Manifest ve kayıt

Bir paket, `deeptutor.plugin/v1` şemasını kullanan statik bir
`deeptutor.plugin.json` dosyası sunar. Tam alanlar için
[`manifest.py`](../../deeptutor/plugins/manifest.py) dosyasını ve
[örnek manifesti](../examples/learning_echo/learning_echo/deeptutor.plugin.json)
okuyun. Manifest; kimlik/sürüm, DeepTutor/API uyumluluğu, izin beyanı, bağımlılık
kapanımı ve türlenmiş uzantıları bildirir. Bilinmeyen alanlar ve geçersiz yollar
reddedilir.

| Uzantı | Çalışma zamanı sözleşmesi |
| --- | --- |
| `tool`, `capability` | Ana makine entry-point protokolü veya onaylı yönetilen JSON worker'ı |
| `loop_capability` | Mevcut paylaşımlı döngü uzantı protokolü |
| `reading_extension` | Sunucu tarafından doğrulanan Reading bağlamı ve sınırlı sonuç türleri |
| `visualizer` | Türlenmiş, paketlenmiş görselleştirici bildirimi |
| `http_route` | Ana makine eklenti ad alanı altında yönetilen worker uç noktası |
| `frontend_page` | Kısıtlayıcı sandbox CSP ile sunulan, bildirilmiş statik varlıklar |
| `persistence_schema`, `app_connector` | Onaylı bildirim/introspection; genel bir geçiş veya bağlayıcı yürütme API'si yok |

Yerleşik kimlikler önceliklidir. Her uzantı kendi türlenmiş protokolünü korur.
Mevcut Python entry-point grupları, bir kök manifest varsa onun onayına uyar;
yeni paketler manifestsiz eski yola güvenmemelidir. Keşif, üçüncü taraf kodunu
içe aktarmadan yalnızca meta verileri okur. [Kayıt defteri](../../deeptutor/plugins/registry.py);
kullanılabilir, onay gerektiren, etkin, devre dışı, uyumsuz, bozuk ve kullanımdan
kaldırılmış durumları birbirinden ayırır.

## Kurulum ve onay

Yaşam döngüsü komutları için `deeptutor plugin --help` çalıştırın. Yönetilen kurulum,
yerel bir wheel'i kabul eder veya gömülü [`catalog.json`](../../deeptutor/plugins/catalog.json)
içindeki gözden geçirilmiş bir girdiyi çözümler. Katalog gezintisi ve sürüm çözümleme
çevrimdışıdır; açık kurulum, sabitlenmiş artefaktı indirir. Rastgele URL ile kurulum
yapan bir yükleyici ve otomatik arka plan yükseltmesi yoktur.

Katalog artefaktları bir HTTPS wheel URL'sini, SHA-256 değerini, boyutu ve platform
meta verilerini bağlar. İndirmeler, pip çalışmadan önce yönlendirmeleri ve boyut/özet
uyuşmazlıklarını reddeder. Yerel yaşam döngüsü, kodu içe aktarmadan önce manifesti
wheel içinden doğrular, sürüme özel bir ortam oluşturur ve yalnızca wheel içeren açık
bir bağımlılık kapanımı kurar. Ana makine yorumlayıcısını değiştirmez.

Onay, normalleştirilmiş manifesti ve artefakt kimliğini bağlar. Onaylamadan önce
geçerli anlık görüntüyü inceleyin. Kurulum, yükseltme, aynı sürümün yeniden kurulumu
ve geri alma, önceki onayı temizler. Onay, yerel olarak devre dışı bırakılmış bir
eklentiyi otomatik olarak etkinleştirmez. Başarısız kurulumlar önceki kullanılabilir
durumu korur; saklanan sürümler geri almayı destekler. Ana makineye kurulu harici
eklentilerin yükseltmelerinde, zaten içe aktarılmış Python modüllerinin değişmesi için
yeniden başlatma gerekir.

Sahibi [`lifecycle.py`](../../deeptutor/plugins/lifecycle.py) dosyasıdır; durum,
çalışma zamanı dizinindeki (runtime home) `data/user/settings/plugins.json` altında
tutulur. API yaşam döngüsü değişiklikleri yönetici yetkilendirmesi gerektirir.
[Eklenti testleri](../../tests/plugins/) manifest, artefakt, işlem, kurtarma ve onay
sınırlarını kapsar.

## Worker protokolü ve iptal

[`runtime.py`](../../deeptutor/plugins/runtime.py), eklenti ortamının Python'unu
kullanarak bir worker modülü başlatır. Worker bildirimleri onaylı manifesti aşamaz.
Eski worker'lar stdin/stdout üzerinden tek bir JSON isteği ve yanıtı alışverişi yapar.

Bir yetenek, açıklamasında `"transport": "ndjson-v1"` ilan edebilir. Bu durumda
`{"kind":"event","event":{...}}` biçiminde JSON satırları yayar, ardından
`{"kind":"complete"}` gönderir. Olaylar normal kalıcı tur akışına girer; worker'lar
paralel bir genel akışa sahip değildir. Tamamlanmadan önce EOF gelmesi ve hatalı
biçimli çerçeveler çalıştırmayı başarısız kılar. İstekler, çerçeveler, çıktı, stderr
ve yürütme süresi sınırlıdır; kuyruklar geri basınç uygular. İptal, işlem grubunu
kapatır ve temizliğin bitmesini bekler. Örnek hem akışlı hem de eski modu destekler.

## HTTP ve statik sayfalar

Yönetilen HTTP route'ları `/api/plugins/{plugin-id}{path}` biçimini kullanır ve
yerleşik route'ların yerini alamaz. Ana makine, bir worker başlatmadan önce onaylı,
etkin ve uyumlu yönetilen durumu çözer ve kimlik doğrulaması yapar. Ana makine kimlik
doğrulaması etkinken, `public` olarak bildirilmiş bir eklenti route'u bile ana makine
oturumu gerektirir: ana makine hesap sınırını aşmaz. `admin` politikası bir yönetici
denetimi ekler. Kullanılamayan eklenti route'ları 404 döndürür.

Worker'lar bildirilen method/yolu, normalleştirilmiş sorgu değerlerini ve sınırlı bir
JSON gövdesini alır; ana makine çerezlerini, bearer token'larını veya kimlik doğrulama
başlıklarını almaz. Yanıtların doğrulanmış JSON durumu/gövdesi ve kısıtlı
`Cache-Control` değeri vardır; yönlendirmeler ve kimlik doğrulama yanıtları ana
makineye aittir. [API testlerine](../../tests/api/test_plugins_router.py) bakın.

Bir statik sayfa, `deeptutor.plugin-frontend-page/v1` şemasını, tek bir giriş noktasını
ve açık bir varlık kapanımını bildirir. Yalnızca onaylı, normal paket dosyaları
sunulabilir; sembolik bağlantılar ve bildirilmemiş varlıklar reddedilir. Kanonik URL
`/api/plugins/{plugin-id}/pages/{extension-id}/` biçimindedir. Göreli varlıklar için
sondaki eğik çizgiyi koruyun.

Sayfalar, `connect-src 'none'` dahil kısıtlayıcı bir CSP ile sandbox'lı bir tarayıcı
bağlamında çalışır; ana makine paketine React/Next kodu enjekte etmezler ve ana makine
API'lerini keyfi olarak çağıramazlar. [`frontend.py`](../../deeptutor/plugins/frontend.py),
[frontend testleri](../../tests/plugins/test_frontend.py) ve
[örnek sayfa manifesti](../examples/learning_echo/learning_echo/frontend/page.json)
dosyalarına bakın.

## Güven sınırları ve doğrulama

İzin bildirimleri ve onay bir işletim sistemi sandbox'ı değildir. Ana makine
entry-point uzantıları ana makine yorumlayıcısında çalışır; yönetilen worker'lar Python
bağımlılıklarını yalıtır ancak ana makine işletim sistemi erişimini korur. Gerçek
paketleri ve bağımlılıkları gözden geçirin. Paketlenmiş tarayıcı sayfalarının kendi
tarayıcı sandbox'ı vardır. Chrome uzantılarının doğrudan yeniden kullanımı desteklenmez.

Manifesti doğrulayın, bir wheel oluşturun, onay/etkinleştirmeyi, worker'ı ve sayfayı
deneyin; ardından devre dışı bırakın/iptal edin ve bir çalıştırmayı iptal edin.
Tek kullanımlık bir çalışma zamanı dizini (runtime home) kullanın.
[Test](TESTING.md) bölümüne ve ayrı olan
[Reading uzantısı bağlam/sonuç kurallarına](READING_EXTENSIONS.md) bakın.
