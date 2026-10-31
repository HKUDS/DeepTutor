# Modüller ve kurulum

[Handbook](README.md) · [İlgili kılavuz](TESTING.md)

DeepTutor tek bir kaynak deposuna ve birbirinden ayrık Python dağıtımlarına sahiptir. `deeptutor`,
paylaşılan tur çalışma zamanını, CLI'yi ve Python SDK'sını barındırır. Özellik dağıtımları, çekirdek
dosyaların üzerine yazmadan aynı paket ad alanına kod ekler. `deeptutor-cli`
bir uyumluluk metapaketidir: çekirdeğe bağımlıdır ve hiçbir Python dosyasına ya da
konsol betiğine sahip değildir. `deeptutor[full]` bir kurulum profilidir; tek tek uygulamaların
kaldırılmasını engelleyecek kalıcı bir metapaket değildir.

Modüler dağıtım ailesi 1.7.0 ile başlar ve her sürümde birlikte
yayımlanmalıdır. 1.6.15 ve önceki paketler önceki düzeni kullanır ve
bu sınırlara sahip değildir. Yerel wheel derlemeleri de desteklenir.

## Kaynak çalışma kopyası

```sh
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
(cd web && npm ci --legacy-peer-deps)
deeptutor module list
deeptutor module disable solve
deeptutor module enable solve
```

Bir çalışma kopyasında tüm kaynak modülleri bulunur. `enable` ve `disable`, wheel kurulumlarıyla
aynı derleme kurallarını çalıştırır. `install` ve `uninstall` ise bilinçli olarak
bir wheel ortamı gerektirir; böylece izlenen kaynak dosyalarını asla silmezler. Kaynak
gereksinimleri `python scripts/sync_module_requirements.py` ile üretilir.
Sapmayı tespit etmek için CI'da `--check` kullanın. `requirements/core.txt` ve `server.txt`
asgari düzeydedir; `full.txt` ise olağan eksiksiz kaynak/Docker çalışma zamanını sağlar.
Kaynak arşivleri ve Docker imajları, `.git` gerekmeden proje dosyası ve modül
derleme betiği üzerinden tanınır. İsteğe bağlı kaynak bağımlılıkları
`python scripts/install_extras.py <extra>` ile eklenebilir; bu komut, kaynak ağacının üzerine yinelenen
özellik wheel'leri kurmadan modül gereksinimlerini çözümler.

## Bağımsız wheel kurulumu

```sh
python scripts/build_modules.py --output dist/modules
python -m venv /tmp/deeptutor-modules
/tmp/deeptutor-modules/bin/python -m pip install --find-links dist/modules deeptutor
/tmp/deeptutor-modules/bin/deeptutor module install solve --wheelhouse dist/modules
/tmp/deeptutor-modules/bin/deeptutor module install renderer-manim --wheelhouse dist/modules
/tmp/deeptutor-modules/bin/deeptutor module disable solve
/tmp/deeptutor-modules/bin/deeptutor module enable solve
/tmp/deeptutor-modules/bin/deeptutor module uninstall solve --dry-run
/tmp/deeptutor-modules/bin/deeptutor module uninstall solve
```

Windows'ta bunların karşılığı olan `Scripts/python.exe` ve `Scripts/deeptutor.exe` dosyalarını kullanın.
Komutları uygulamayla aynı `DEEPTUTOR_HOME` ile çalıştırın. Python paketleri
ortam başına kurulur; etkin durum `<home>/data/system/modules.json` içinde tutulur ve
tek bir öğrenciye değil, o dağıtıma uygulanır.
`--wheelhouse`, paket dizinini yerel olarak derlenmiş wheel'lerle tamamlar.

API için `server`, ardından paketlenmiş Web varlıkları için `web` kurun. Web wheel'i,
`deeptutor start` için `scripts/prepare_web_package.py` tarafından üretilen varlıkları
gerektirir; kaynak geliştirme sunucusu ise çalışma kopyasındaki `web/` dizinini kullanır. Derleme ve
sürüm otomasyonu, wheel ailesini derlemeden önce Web varlıklarını hazırlar.

## 1.6.15'ten yükseltme

Eski süreci durdurun ve çalışma zamanı dizinini (runtime home) yedekleyin. Önce aday wheel'leri
paketlenmiş Web varlıklarıyla derleyin. Eski ortamın tek kullanımlık bir kopyasında,
`python -m pip install --upgrade --find-links dist/modules
"deeptutor[full]==<candidate-version>"` komutuyla yükseltme yapın. Eski `deeptutor-cli`
kuruluysa önce `python -m pip uninstall deeptutor-cli` ile kaldırın,
ardından yükseltme komutunu çalıştırın; isterseniz yeni uyumluluk takma adını da ekleyin.
Eski CLI, yeni çekirdekle aynı Python dosyalarına sahiptir: pip, eski CLI'yi kaldırmadan önce
yeni çekirdek bağımlılığını kurar ve bu da yeni dosyaları siler.
Eski CLI'yi önce kaldırmak bu çakışmayı önler ve çalışma zamanı dizinindeki (runtime home) verileri korur.
Yalnızca CLI geçişi için, bu kaldırma işleminden sonra `deeptutor-cli==<candidate-version>` kurun. Yayımlanmış
daha eski bir sürümün çözümlenmesini önlemek için tam aday sürümü kullanın. `DEEPTUTOR_HOME` değerini
değiştirmeden bırakın, `pip check` çalıştırın,
`deeptutor module list` çıktısını inceleyin; gerçek ortamı yükseltmeden önce sohbeti, kalıcı oturumları ve Web
başlatmayı deneyin. Kullanıcı verisinin tek kopyası üzerinde asla test yapmayın. Yalnızca çekirdeğin yükseltilmesi,
eski tam uygulama profilini korumaz.

`deeptutor/__version__.py`, kaynak CLI uyumluluk paketi dahil tüm derlemeler için sürüm kaynağıdır.
Extra'lar `tool.deeptutor.optional-dependencies` içinde şablon olarak tanımlanır; hem setuptools hem de
modül derleyicisi iç sürüm sabitlemelerini bu sürüme göre çözümler. Bir sürüm artışı,
bağımlılıkların önceki modül ailesini işaret etmesine yol açmamalıdır.

## Sahiplik ve derleme

`deeptutor/modules/manifests/*.json` yetkili kataloğdur. Her manifest; yolları, bağımlılık gereksinimlerini,
tur yeteneklerini, döngü uzantılarını, araç adlarını, API yönlendiricilerini ve yetkilendirme politikalarını,
CLI gruplarını, gezinme yollarını ve arka plan servis geri çağrılarını sahiplenir. En uzun eşleşen yol kazanır.
Paylaşılan protokoller ve hafif bağlam meta verileri çekirdekte kalır; özellik uygulamaları kendi
dağıtımlarında kalır. Derleyici, çakışan wheel dosyalarını reddeder.

| Modül ailesi | İçerik |
| --- | --- |
| core | Kalıcı turlar, sohbet, soru sorma, paylaşılan araçlar, CLI/SDK, ayarlar ve oturumlar |
| server / web | API ve kimlik doğrulama adaptörleri / paketlenmiş Next.js varlıkları |
| solve / questions / research | Planlama döngüsü / soru üretimi / araştırma hattı |
| visualize / renderer-manim | HTML/SVG/grafik görselleştiriciler / isteğe bağlı Manim hattı |
| video-lesson / audio-overview | Tarayıcı dersleri / sesli özet üretimi |
| knowledge / parsing | Getirme ve içe aktarma / belge ayrıştırma uygulamaları |
| reading / mastery / books | Okuma ve izleme / Guided Learning / kitap uygulaması |
| memory / notebook / co-writer / calendar | İsteğe bağlı uygulama servisleri ve rotaları |
| partners / providers | Eşlik eden çalışma zamanı ve kanal SDK'ları / isteğe bağlı model sağlayıcı SDK'ları |
| parser-* | Ek ayrıştırıcı bağımlılık dağıtımları; parsing gerektirir |

Bağımlılıklar açıktır ve döngü içermez. Örneğin reading, uygulaması bu depoları kullandığı için
şu anda knowledge, parsing, mastery ve notebook modüllerini gerektirir. Books ise standart
bölüm blokları ve seçili kaynağa dayalı üretim için questions, visualize ve mastery modüllerini de gerektirir.
İsteğe bağlı entegrasyonlar ayrıca listelenir: Calendar, Mastery olmadan çalışır; Research ve Questions,
Knowledge olmadan çalışır; Parsing ise knowledge depolamasını asla içe aktarmaz. Kullanılamayan
bir entegrasyonun seçilmesi bir kurulum ipucu döndürür. Knowledge Frontier hem
Research hem de Knowledge gerektirir; bir araç katkısı, sahibi olan uygulamanın her kullanımına bu modülleri
zorlamadan ek gereksinimler bildirebilir.
Bir bağımlılığı devre dışı bırakmak, onu kullanan etkin modüller devre
dışı bırakılana kadar engellenir. Bir bağımlılığı kaldırmak, devre dışı olanlar dahil kurulu herhangi bir
bağımlı modül kaldığı sürece engellenir. Etkinleştirme/kurulum, bağımlılıkları
sırayla çözümler. Çekirdek devre dışı bırakılamaz veya kaldırılamaz.

Yükleyici, bulunmayan veya devre dışı yetenek/döngü uygulamalarını içe aktarmaz.
İstek şemaları tembel yüklenir. Döngü uzantıları tur başına bir kez örneklenir ve
etkinleştirme, bağlam değiştikçe yeniden değerlendirilir; örnekler turlar arasında asla paylaşılmaz. Yönetilen
eklenti yetkisinin geri alınması yine denetlenir. Arka plan başlatma/durdurma geri çağrıları,
kısmi başlatma geri almaları için eşli kalır. Mevcut API kimlik doğrulama politikaları
katkıda bulunulan yönlendiricilerde geçerli kalır; modül durumu bir izin vermek anlamına gelmez.

`GET /api/modules` kimlik doğrulaması gerektirir ve kurulu, etkin ve hazır durumlarını
ayrı ayrı gösterir. Runtime ayarları sayfası bu durumları ve çevrimdışı
komutları görüntüler. Kenar çubuğu ve sayfa erişimi gezinme sahipliğini kullanır; API rota derlemesi de
bulunmayan modülleri, paylaşılan yönlendiricilerdeki özelliğe özgü yollar dahil, dışarıda bırakır.
Hazır olma denetimleri paket gereksinimlerini, eşleşen çekirdek/modül sürümlerini ve harici
yürütülebilir dosyaları kontrol eder. Yapılandırılmış sağlayıcı kimlik bilgileri ve servis bağlantısı
mevcut ayarlar hazır olma sisteminde kalır.

## Yaşam döngüsü garantileri

Resmî modüller tek bir yorumlayıcıyı paylaşır. Çalışan uygulama konteynerleri
paylaşılan bir ortam kirası (lease) tutar; modül değişiklikleri, süreçler arasında özel bir kira gerektirir. Farklı Python
ortamları aynı dizini paylaştığında, dağıtım seçimini ikinci bir kira korur. Paketleri veya seçimi değiştirmeden önce
CLI turlarını ve API worker'larını durdurun.
Doğrudan harici `pip` komutları bu danışma niteliğindeki kilitle engellenemez.

Kurulum önce bağımlılıkları çözümler, mevcut bir paket sürümünün değiştirilmesini reddeder
ve ortamı değiştirmeden önce çözümlenen tam yapıtları derler.
Paket ekledikten sonra kurulum başarısız olursa, seçimin kaydedilememesi de dahil olmak üzere,
yeni eklenen dağıtımlar kaldırılır. Hatalı biçimlendirilmiş seçim,
herhangi bir paket değişikliğinden önce reddedilir. Seçim yalnızca paket işlemleri başarılı olduktan sonra atomik olarak değiştirilir.
Bağımlılık çakışmaları için yeni bir ortam veya açık bir ortam yükseltmesi kullanın.
Bu, bir makine çökmesi boyunca atomik bir dosya sistemi işlemi değildir; yarıda kalmış bir makine için
standart pip onarımı/yeniden kurulumu kurtarma yolu olmaya devam eder.

Kaldırma yalnızca seçilen dağıtımı siler. Paylaşılan bağımlılıklar korunur,
çünkü diğer uygulamalar bunları kullanıyor olabilir. Kullanıcı ayarları, oturumlar, not defterleri,
bilgi tabanları, üretilen yapıtlar ve kimlik bilgileri asla temizlenmez. Yeniden kurulum,
korunan verileri kullanır. Örtük bir veri silme komutu yoktur.

Çalışan bir ayar/kurulum oturumundan ayrıştırıcı paketi kurulumu artık
çevrimdışı bir modül komutu döndürür. Etkin turların altında artık paketleri yükseltmez.
Model ağırlığı indirmeleri, Python kodunu değiştirmedikleri için arka plan işleri olarak kalır. Üçüncü taraf yönetilen
eklentiler mevcut yalıtılmış ortamlarını korur.

## Üçüncü taraf worker uzantıları

Yönetilen eklenti worker'ları, resmî modül wheel'lerinden ayrı olarak kendi ortamlarını ve
yaşam döngülerini kullanır. [eklenti akışı ve iptal](PLUGINS.md#worker-protokolü-ve-iptal)
bölümüne ve [çalıştırılabilir örneğe](examples/learning_echo/README.md) bakın.

## Doğrulama

```sh
python scripts/sync_module_requirements.py --check
python -m pytest tests/modules tests/test_packaging_metadata.py
python scripts/build_modules.py --output dist/modules
python scripts/check_module_install.py --wheelhouse dist/modules --extended
```

Kurulum duman testi, tek kullanımlık bir sanal ortam oluşturur, yerel bir sahte
model kullanır (sağlayıcı kimlik bilgisi gerekmez), çekirdek sohbeti ve kalıcı yeniden oynatmayı denetler, Solve'u kurar,
çalıştırır, kaldırır, kalıcı dosyaları doğrular, çekirdeği yeniden denetler, ardından
Solve'u yeniden kurar. Genişletilmiş mod; Parsing, Research ve Calendar modüllerini
Knowledge veya Mastery olmadan kurar, ayrıştırmayı ve önbelleğini ile bağımsız araştırma
ve takvim yollarını çalıştırır, ardından Solve'u ve korunan veriyi doğrularken her modülü kaldırır.
Kaynak yalıtım testleri ayrıca 25 modülün her biri için yeni bir alt süreçte bildirilmemiş
içe aktarmaları yasaklar ve katkılarını bir araya getirir.
Manim ayrıca sistem render kütüphanelerine, FFmpeg'e ve
LaTeX'e ihtiyaç duyar. Render işleyicisindeki değişikliklere bir render ve iptal testi eşlik etmelidir.
Web uygulaması tek bir ön yüz dağıtımı olarak kalır; bağımsız olarak değiştirilebilen
üçüncü taraf ön yüz paketleri bu Python modül sözleşmesinin kapsamı dışındadır.

## Uygulama ve doğrulama

- [deeptutor/modules/manifests/](../../deeptutor/modules/manifests/)
- [scripts/build_modules.py](../../scripts/build_modules.py)
- [scripts/check_module_install.py](../../scripts/check_module_install.py)
