# Immersive Reading uzantıları

[El kitabı](README.md) · [İlgili kılavuz](PLUGINS.md)

Immersive Reading, sunucu tarafı paketleri `deeptutor.reading_extensions` Python
entry-point grubu üzerinden keşfeder. DeepTutor bu grupta sesli okuma, çalışma
rehberliği, kelime bilgisi, sınav ve açık hedefli çeviri uzantılarını birlikte sunar;
hiçbir uzantı kurulu değilse Reader bir uzantı araç çubuğu göstermez.

Bir entry point, doğrulanmış bir `manifest` ve `run_action(action, context)`
metoduna sahip bir nesneye veya sınıfa çözümlenir. Geçerli protokol sürümü `1`'dir.

```toml
[project.entry-points."deeptutor.reading_extensions"]
example = "example_reading_plugin:ExampleExtension"
```

```python
from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingExtensionManifest,
    ReadingExtensionResult,
)


class ExampleExtension:
    manifest = ReadingExtensionManifest(
        id="example",
        version="1.0.0",
        name="Example",
        actions=[ReadingAction(id="explain", label="Explain")],
        result_types=["card"],
    )

    def run_action(self, action, context):
        return ReadingExtensionResult(
            type="card",
            title="Example",
            payload={"body": context.visible_text[:500]},
        )
```

## Güvenlik sınırı

- Genel Reading API kimlik doğrulama politikası, uzantı route'larını korur.
- Sunucu; materyali, konumlandırıcıyı, kaydedilmiş kaynak çapasını ve saklanan birim
  metnini çözümler; tarayıcı bunları keyfi değerlerle değiştiremez.
- Bir seçim yalnızca saklanan birimde aynen geçiyorsa iletilir.
- Uzantılar, doğrulanmış dört sonuç türünden birini döndürür: `card`, `quiz`,
  `feedback` veya `browser_speech`.
- Sonuçların serileştirilmiş boyut üst sınırı 64 KB'tır. Sınav ve konuşma yükleri
  ek olarak biçim ve uzunluk doğrulamasından geçer.
- Protokolün 60,000 karakterlik bağlam üst sınırından büyük birimler, bir uzantı
  çağrılmadan istemci hatasıyla reddedilir.
- Eylemlerin 30 saniyelik yürütme zaman aşımı vardır ve aşıldığında standart,
  kurtarılabilir kullanılamazlık yanıtını döndürürler. Bir iş parçacığında zaten çalışan
  eşzamanlı bir Python işleyicisi güvenle sonlandırılamaz; bu nedenle her uzantının tek
  bir özel worker'ı vardır ve zaman aşımından sonra devresi açık kalır; sonraki çağrılar,
  işlem genelindeki iş parçacığı havuzunu tüketmek veya o havuza iş kuyruğa almak yerine
  hızlıca başarısız olur. Takılan uzantıyı düzelttikten veya kaldırdıktan sonra DeepTutor'ı
  yeniden başlatın.
- Sonuç verileri React metni olarak işlenir. Uzantılar Reader'a JavaScript veya ham HTML
  gönderemez.
- Keşif ve yürütme hataları yalıtılmıştır. Bozuk bir isteğe bağlı paket, belgelerin veya
  diğer uzantıların açılmasını engelleyemez.

Protokol değişiklikleri `1` sürümü içinde geriye dönük uyumlu kalmalıdır. Gelecekteki
uyumsuz bir sözleşme, mevcut bir alanın anlamını değiştirmek yerine yeni bir protokol
sürümü kullanmalıdır.

## Uygulama ve doğrulama

- [deeptutor/reading/extensions.py](../../deeptutor/reading/extensions.py)
