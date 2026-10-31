# Konuşma yapılandırması ve adaptör geliştirme

[El kitabı](README.md) · [Ajan kurulumu](AGENT_SETUP.md) · [Video ile öğrenme](watching-workspace.md)

TTS (konuşma sentezi) ve STT (konuşma tanıma), sohbet modelinden bağımsız olarak Speech settings içinde kendi sağlayıcı profillerine ve varsayılanlarına sahiptir.

## Yapılandırma ve doğrulama

1. Uygulanmış bir sağlayıcı seçin; uç noktasını, tam model/kaynak
   kimliğini ve kimlik bilgisi türünü girin.
2. Destekleniyorsa sesleri sağlayıcı üzerinden keşfedin. Ses kimlikleri kalıcı,
   pakete dahil bir katalog değildir; hesaba özel sesler ve model kimlikleri
   düzenlenebilir kalır. Listelenen bir ses, hesap yetkisinin olduğunu kanıtlamaz.
3. O model ailesinin desteklediği dili, biçimi ve diğer seçenekleri belirleyin.
4. Kısa bir örneği önizleyin, ardından varsayılanı kaydedin/seçin. Önizleme,
   kaydedilmiş varsayılanı değiştirmeden mevcut formu kullanır.
5. Kaydettikten sonra gerçek sesli okuma veya yazıya dökmeyi doğrulayın. Yalnızca
   model listesinin başarılı olması, konuşma sentezinin veya tanımanın çalıştığını
   kanıtlamaz.

Önizleme sağlayıcıyı çağırır ve kullanım ücreti doğurabilir. Form değişiklikleri
eski önizlemeyi geçersiz kılar; devam eden bir önizleme iptal edilebilir. İstek
zaman aşımı 5–600 saniye kabul eder ve varsayılanı 60'tır. Kısa örnekler,
yapılandırma hatalarını ayırt etmeye yardımcı olur.

## Sağlayıcı sınırları

- **Volcengine Speech:** Speech kimlik bilgileri, Ark LLM anahtarlarından farklıdır.
  Adaptör, Speech API Key kimlik doğrulamasını ve eski App ID/erişim belirteci
  biçimini kabul eder. TTS kaynağını ve ses ailesini eşleştirin. STT, bir kayıt
  dosyası API'si kullanır; ses normalleştirme için sistem FFmpeg'i gerekebilir.
- **Aliyun DashScope:** Qwen3 TTS ve Qwen-Audio TTS'in ayrı yerel uç noktaları ve
  parametreleri vardır. Adaptör, desteklenen resmi uyumlu mod tabanlarını
  normalleştirir; özel bir uç nokta seçilen protokolü uygulamalıdır. Anahtarı ve
  uç nokta bölgesini eşleştirin. Eski bir örneğin hâlâ kullanılabilir olduğunu
  varsaymak yerine sesleri keşif ve gerçek önizleme ile doğrulayın.
- **Diğer adaptörler:** uyumlu bir sohbet uç noktası, uyumlu bir konuşma API'sinin
  varlığını göstermez. Desteklenen sesleri ve biçimleri model seçenekleri ve
  canlı keşif belirler.

Kimlik bilgisi içeren yanıtları açığa çıkarmadan; kimlik doğrulama, bölge/model,
izin, hız sınırı, zaman aşımı ve ses indirme hatalarını ayrı ayrı koruyun.
Sınırsız yeniden denemeler eklemek yerine iptali ve yapılandırılmış zaman aşımlarını koruyun.

## Kaynak haritası

| Sorumluluk | Uygulama |
| --- | --- |
| Profiller ve çözümleme | [voice/config.py](../../deeptutor/services/voice/config.py) |
| Model/parametre ipuçları | [voice/options.py](../../deeptutor/services/voice/options.py) |
| Ses keşfi | [voice/discovery.py](../../deeptutor/services/voice/discovery.py) |
| Önizleme | [voice/preview.py](../../deeptutor/services/voice/preview.py) |
| Sağlayıcı protokolleri | [voice/adapters/](../../deeptutor/services/voice/adapters/) |
| Ses dönüştürme | [voice/audio.py](../../deeptutor/services/voice/audio.py) |

Bir adaptör eklerken kimlik bilgisi işlemeyi, uç nokta normalleştirmeyi, kod çözmeyi,
zaman aşımı/iptali ve hata maskelemeyi test edin. Canlı kontrolleri, sahte (mock)
protokol testlerinden ayrı raporlayın. Sağlayıcı katalogları, kullanılabilirlik ve
faturalandırma bu deponun dışında kalır.
