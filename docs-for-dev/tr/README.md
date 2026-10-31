# DeepTutor geliştirici ve ajan el kitabı

> 🇹🇷 Bu dizin, [İngilizce el kitabının](../README.md) Türkçe çevirisidir. Kod, komut ve yapılandırma anahtarları orijinaliyle aynıdır; içerik farklılaşırsa İngilizce (kaynak) sürüm esas alınır.

DeepTutor'ı kurmak, sorunlarını teşhis etmek veya değiştirmek için buradan başlayın. Bu el kitabı
**1.7.0 kaynak ağacını** anlatır; başka bir sürümle çalışırken aynı etiketteki
dokümantasyonu kullanın. Sürüm için yetkili kaynak
[`deeptutor/__version__.py`](../../deeptutor/__version__.py) dosyasıdır. Aşağıdaki komutlar,
bir sayfa aksini belirtmedikçe depo kök dizininden çalıştırılır.

## Okuma yolunu seçin

| Göreviniz | Sırayla okuyun | Tamamlandığının kanıtı |
| --- | --- | --- |
| Uygulamayı kurmak ve yapılandırmak | [Ajan kurulumu](AGENT_SETUP.md) → [Depolama](DATA_STORAGE.md) | Bağımlılıklar, modül hazır olma durumu, gerçek model yanıtı, erişilebilir uygulama |
| Mevcut bir kurulumu onarmak | [Kurulum sorun giderme](AGENT_SETUP.md#6-sorun-giderme) → aşağıdaki ilgili konu | Başarısız olan özgün eylem aynı örnekte ve çalışma alanında çalışıyor |
| Bir değişiklik geliştirmek | [Geliştirme](DEVELOPMENT.md) → [Mimari](ARCHITECTURE.md) → [Test](TESTING.md) | Odaklı regresyon testi ve geçerli proje kontrolleri |
| Bir araç veya yetenek eklemek | [Araç ve yetenek sözleşmeleri](TOOLS_AND_CAPABILITIES.md) → [Modüller](MODULES.md) | Kayıt, kullanılabilirlik, yürütme ve nihai sonuç testleri |
| Üçüncü taraf eklentisi geliştirmek | [Eklentiler](PLUGINS.md) → [Çalıştırılabilir Learning Echo örneği](examples/learning_echo/README.md) | Wheel, manifest, onay, worker ve ön yüz kontrolleri |
| Akışı veya belleği incelemek | [Olaylar ve ilerleme](EVENTS_AND_PROGRESS.md) → [Çalışma zamanı tasarımı](RUNTIME_DESIGN.md) | Kalıcılık/yeniden oynatma ve iptal kanıtı |
| Dağıtmak veya yükseltmek | [Modüller](MODULES.md) → [Konteynerler](CONTAINERIZATION.md) → [Depolama](DATA_STORAGE.md) | Eşleşen sürümler, korunan veriler, hazır olma durumu ve temsili bir tur |

Terminal kullanabilen bir ajan, düzenlemeden önce bu dizini, [AGENTS.md](../../AGENTS.md) dosyasını ve
görevin kılavuzunu okumalıdır. [SKILL.md](../../SKILL.md), CLI için derli toplu
başvuru kaynağıdır. Bir örneği izlemeden önce çalışma kopyasını (checkout), çalışma ağacındaki değişiklikleri, Python ortamını ve
çalışma zamanı dizinini (runtime home) inceleyin. Mevcut kullanıcı verilerini ve
kimlik bilgilerini, tek kullanımlık test fixture'larından ayrı tutun. Başarısız bir
kurulumu yeniden kurmaya karar vermeden önce teşhis edin.

## Konu haritası

### Çalışma zamanı ve eklenti geliştirme

- [Mimari ve kaynak sahipleri](ARCHITECTURE.md): giriş noktaları, kalıcı
  turlar, ön yüz sınırları ve yapılandırma.
- [Araçlar ve yetenekler](TOOLS_AND_CAPABILITIES.md): tek seferlik araçlar,
  turu devralan işlem hatları, bağlam geçitleri ve sonuç zarfları.
- [Modüller](MODULES.md): dağıtım sahipliği, kurulum ve yaşam döngüsü.
- [Eklentiler](PLUGINS.md): manifestler, inceleme, worker'lar, HTTP ve statik sayfalar.
- [Okuma uzantıları](READING_EXTENSIONS.md): doğrulanmış seçim bağlamı ve
  sınırlı sonuçlar.
- [Olaylar ve ilerleme](EVENTS_AND_PROGRESS.md): tur yeniden oynatma ile dizinleme
  ilerlemesi ve süreç yerelindeki bildirimler arasındaki fark.
- [Çalışma zamanı tasarımı](RUNTIME_DESIGN.md): tembel yükleme, yalıtılmış ayrıştırma,
  özel model geçmişi ve istem önbelleği gözlemlenebilirliği.
- [Claude model senkronizasyonu](CLAUDE_MODEL_SYNC.md): SDK keşfi, model
  katalogları ve yalıtılmış sağlayıcı oturumları.
- [Uzak Hermes arka ucu](remote-hermes-backend.md): gateway protokolü ve
  Connected Agents entegrasyonu.

### Depolama, dağıtım ve özellik sözleşmeleri

- [Veri depolama](DATA_STORAGE.md) ve [çalışma alanları](workspaces.md): çalışma
  zamanı dizini (runtime home), hesap/çalışma alanı kapsamı, yedekler, kaynak atama ve taşıma.
- [Sunucu çalışma alanı seçici](SERVER_WORKSPACE_PICKER.md): izin verilen sunucu
  klasörlerine göz atma ve çalışma alanı kökü seçme.
- [Konteynerleştirme](CONTAINERIZATION.md) ve [istek denetimi](SECURITY_GUARD.md):
  dağıtım yapılandırması, OAuth geri çağırma portları ve proxy sınırları.
- [Bilgi taşıma](KNOWLEDGE_MIGRATION.md), [dizinleme kurtarma](INDEXING_RECOVERY.md)
  ve [kaynak görselleri](SOURCE_VISUALS.md): içe alma, yayımlama, özgün
  kanıt ve görsel değerlendirme.
- [Bilimsel araştırma](SCIENTIFIC_RESEARCH.md): makale araçları, kanıt ve MCP
  yetkilendirmesi.
- [Alıştırma](PRACTICE.md): soru içe aktarmaları, tekrar kayıtları ve zamanlama.
- [Video öğrenme](watching-workspace.md) ve [ses](VOICE_CONFIGURATION.md):
  Reading medya taşıma, altyazılar, konuşma adaptörleri ve doğrulama.
- [Yanıt kalitesi teşhisi](REASONING_SAFETY_CHECKLIST.md): yeniden üretilebilir
  getirme, atıf, bağlam ve değerlendirme hataları.

## Bu el kitabını yararlı tutma

Her sözleşme için tek bir kanonik sayfa tutun ve ona bağlantı verin. Her konu,
uygulama sahiplerine veya regresyon testlerine işaret etmelidir. Komutlar, route'lar, sahiplik veya depolama
değiştiğinde etkilenen örnekleri güncelleyin; üretilmiş şemalar ve modül
manifestleri düzyazıdan önceliklidir. Bir kontrolün neyi kanıtladığını, sağlayıcı/ağ
veya platform sınırlamalarıyla birlikte kaydedin.

Görev planlarını, tek seferlik test sayılarını, ekran görüntülerini, özel yolları, indirilmiş
başvuru depolarını ve ilgisiz ürün araştırmalarını bu el kitabının dışında tutun.
Yürütme kanıtı için PR'ları veya yerel olarak yok sayılan çıktıları kullanın. Bir tasarım önerisi,
uygulaması bulunup doğrulanabilene kadar geçerli davranış sayılmaz.
