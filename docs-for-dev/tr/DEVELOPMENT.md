# DeepTutor geliştirme

[El kitabı](README.md) · [Mimari](ARCHITECTURE.md) · [Test](TESTING.md)

## Kaynak ortamı hazırlama

Python 3.11–3.14, Node.js 22 LTS, sağlayıcı yapılandırması ve hazır olma durumu
için [Ajan kurulumu](AGENT_SETUP.md) belgesini izleyin. Kaynak çalışma kopyası
(checkout) tüm modülleri sunar; düzenlenebilir çekirdekten önce dış
bağımlılıklarını kurun:

```bash
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
python scripts/install_extras.py dev
cd web
npm ci --legacy-peer-deps
cd ..
```

İsteğe bağlı kaynak bağımlılıkları için `scripts/install_extras.py` betiğini
kullanın. Özellik wheel'lerini düzenlenebilir bir checkout üzerine kurmak kaynak
sahipliğini belirsizleştirebilir; [wheel yaşam döngüsü testi](MODULES.md#doğrulama)
için ayrı bir ortam kullanın. FFmpeg ve LaTeX gibi sistem çalıştırılabilir
dosyaları, onlara ihtiyaç duyan özellikler için ayrı önkoşullar olarak kalır.

Güncellemeden önce `git status`, etkin dalı ve uzak depoları inceleyin.
`dev` dalına karşı geliştirin; PR hedefleri için
[katkı politikasını](../../CONTRIBUTING.md) izleyin. Eşzamanlı çalışmanın yalıtım
gerektirdiği durumlarda uygun bir görev checkout'unu yeniden kullanın veya ayrı
bir worktree kullanın. İlgisiz düzenlemeleri koruyun. Çalışma zamanı verilerini
ve test çıktılarını Git dışında tutun.

## Özel bir çalışma zamanı dizini kullanma

`DEEPTUTOR_HOME`, `data/` dizininin kendisi değil, onu barındıran dizindir.
Açık ve özel bir geliştirme dizini (runtime home) seçin ve her komutta onu
kullanın. Örneğin, yeni bir kabukta:

```bash
export DEEPTUTOR_HOME="$HOME/.local/share/deeptutor-dev"
deeptutor init --non-interactive
deeptutor config show
deeptutor module list
```

Fixture'ları mevcut bir öğrenenin çalışma zamanına yönlendirmeyin. Content
Workspace ayrı bir depolama ve yetkilendirme kapsamıdır; bkz.
[çalışma alanları](workspaces.md). Uygulama projenin `.env` dosyasını otomatik
olarak yüklemez.

## Çalıştırma ve inceleme

Birleşik başlatıcı için `deeptutor start` komutunu kullanın ve gerçek URL'leri
çıktısından okuyun. Ayrı geliştirme süreçleri için API'yi ve ön yüzü, seçtiğiniz
aynı çalışma zamanı dizini ile iki ayrı terminalde çalıştırın:

```bash
# Terminal 1: API, with reload
deeptutor serve --host 127.0.0.1 --port 8001 --reload
```

```bash
# Terminal 2: frontend, from web/
DEEPTUTOR_API_BASE_URL=http://127.0.0.1:8001 npm run dev
```

Boş portlar seçin; ilgisiz hizmetleri durdurmayın. Tarayıcı isteklerinin ön yüz
proxy'si üzerinden amaçlanan API'ye ulaştığını doğrulayın. Yalnızca dinleyen bir
ön yüz; sağlayıcının, modülün veya turun hazır olduğunu göstermez. Doğrulamak
için `deeptutor doctor --format json` komutunu ve özgün kullanıcı işlemini
kullanın.

## Değişikliği sahibinde yapma

1. Davranışı minimal bir sentetik fixture ile yeniden üretin. Sahibin adaptör,
   paylaşılan çalışma zamanı, yetenek, araç, özellik deposu, sağlayıcı veya ön
   yüz izdüşümü olup olmadığını belirleyin.
2. En yakın uygulamayı ve testlerini okuyun. API değişiklikleri için istek
   doğrulamasını kimlik doğrulama, hesap/çalışma alanı çözümlemesi, kalıcılık,
   olaylar ve kullanıcı arayüzü tüketimi boyunca izleyin.
3. İkinci bir çalışma zamanı, yol çözümleyici, sağlayıcı istemcisi veya depolama
   soyutlaması eklemek yerine o sahibi değiştirin. Paylaşılan protokoller
   içe aktarma açısından hafif kalır.
4. Etkilenmişse modül bildirimlerini, istek sözleşmelerini, istemleri ve yerel
   ayar dizelerini güncelleyin. Türetilmiş dosyaları kendi sahibi olan betiklerle
   yeniden üretin.
5. [Değişikliğe uygun kontrolleri](TESTING.md) çalıştırın, özgün işlemi yeniden
   üretin ve PR'da doğrulama sınırlarını açıklayın.

Alt süreçler için açık argüman listeleri ve `shell=False` kullanın; iptal
durumunda süreç ağacı temizliğini koruyun. Depolamayı genel bir veri yolu
oluşturmak yerine mevcut hesap ve çalışma alanı bağlamı üzerinden çözümleyin.
Kimlik bilgilerini veya özel sağlayıcı yeniden oynatma meta verilerini hiçbir
zaman tarayıcı yanıtlarına döndürmeyin.

## Üretilmiş dosyalar ve dokümantasyon

Depo, üretilmiş API sözleşmelerini, requirements dosyalarını ve bağımlılık
kilitlerini kasıtlı olarak izler. Üreteçlerini veya yetkili girdilerini
güncelleyin, ardından yeniden üretin. `web/.next*`, kurulu bağımlılıklar,
bytecode, günlükler ve elle yapılan kabul artifact'leri izlenmeden kalır.

Herkese açık bir davranış değiştiğinde ilgili el kitabı konusunu ve README
bağlantılarını güncelleyin. Yeniden kullanılabilir çalıştırılabilir örnekleri bu
el kitabının [`examples/`](examples/learning_echo/README.md) dizinine koyun.
Komut örneklerini depo kökünden kullanılabilir tutun ve kişisel makine
yollarından kaçının.
