# Claude Code model keşfi

Claude Code bağlı ajan arka ucunun model Sync eylemi, CLI'nin güncel model
kataloğunu almak için resmî Python Agent SDK'sını kullanabilir. İsteğe bağlı
bağımlılığı bir kaynak çalışma kopyasından kurun:

```bash
python scripts/install_extras.py claude-code
```

Mevcut Claude Code oturumunu ve ortamını kullanın. Sync, PATH üzerindeki
`claude` yürütülebilir dosyasını tercih eder; yüklü değilse SDK'nın paketlenmiş
CLI'sini kullanır. SDK başlatma yanıtı görünen adları ve çözümlenmiş model
kimliklerini sağlar; bunlar mevcut `claude_models_cache.json` dosyasında saklanır.
Hiçbir çıkarım isteği yapılmaz ve bu yanıttaki hesap meta verileri saklanmaz.

Önerilen/varsayılan satır atlanır, çünkü arayüz zaten CLI varsayılanını sunar.
Devre dışı girdiler ve yinelenen çözümlenmiş kimlikler atlanır. Çözümlenmiş
kimlik döndürmeyen eski CLI'ler, döndürdükleri takma adları korur; açık `[1m]`
varyantları ayrı kalır. Modeller, sabit kodlanmış bir aile listesiyle sınırlı
değildir.

SDK eksikse, zaman aşımına uğrarsa veya katalog döndürmezse Sync, mevcut POSIX
terminal seçicisine geri döner. Her iki keşif yöntemi de başarısız olursa önceki
önbellek olduğu gibi kalır. Eşitlenmiş önbellek yokken takma ad önerileri belirli
sürüm numaraları iddia etmez. Bir modeli listelemek hesap yetkisini veya kalan
kotayı doğrulamaz; Sync her modeli bir istem göndererek test etmez.

SDK oturumu geçici bir klasörde çalışır; proje ayarları, yerel araçlar ve örtük
MCP yapılandırmaları devre dışıdır. Kimlik doğrulamayı Claude Code yönetir; bu
özellik kimlik bilgilerini kopyalamaz ve birincil bir model sağlayıcısı eklemez.
