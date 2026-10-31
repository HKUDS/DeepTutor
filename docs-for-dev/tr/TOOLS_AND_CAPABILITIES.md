# Araçlar ve yetenekler

[El kitabı](README.md) · [Mimari](ARCHITECTURE.md) · [Modüller](MODULES.md) · [Eklentiler](PLUGINS.md)

## İki sözleşme

[`BaseTool`, `ToolDefinition` ve `ToolResult`](../../deeptutor/core/tool_protocol.py),
bir model tarafından seçilen tek bir işlemi tanımlar. Bir araç argümanları
doğrular, işlemi gerçekleştirir ve içerikle birlikte yapılandırılmış
meta veri/hata durumu döndürür. Kullanılabilirlik, her kaynağa erişme iznine
eşdeğer değildir.

[`TurnCapability` ve `CapabilityManifest`](../../deeptutor/core/capability_protocol.py),
bir turun sahibi olan bir işlem hattını tanımlar. Bir yetenek `UnifiedContext`
tüketir ve akış olayları yayar. Yetenekler, yanıt yükü ve `cost_summary` için
[`emit_capability_result()`](../../deeptutor/agents/_shared/capability_result.py)
işlevinde birleşir; başka bir tamamlanma zarfı icat etmeyin.

Yerleşik katalog, [`modules/manifests/`](../../deeptutor/modules/manifests/)
dizininden [`builtin_capabilities.py`](../../deeptutor/runtime/bootstrap/builtin_capabilities.py)
tarafından türetilir. Her kaynak özelliğinin yalnızca çekirdek wheel
ortamında kullanılabilir olduğunu varsaymak yerine mevcut kurulumu incelemek
için `deeptutor module list`, `deeptutor plugin list` ve
`deeptutor plugin info` komutlarını kullanın.

## Bağlama kuralları

Kullanıcının açıp kapatabildiği sekiz araç `brainstorm`, `web_search`,
`paper_search`, `zotero_search`, `reason`, `geogebra_analysis`, `imagegen` ve
`videogen` araçlarıdır. [`tools/builtin/__init__.py`](../../deeptutor/tools/builtin/__init__.py)
içindeki `USER_TOGGLEABLE_TOOL_NAMES` yetkili listedir; CLI `--tool` seçeneği
bu listeden seçim yapar.

`CONFIGURABLE_BUILTIN_TOOL_NAMES`, araştırma, getirme, bellek, not defteri,
yürütme ve ertelenmiş araç keşfi dahil bağlama göre kapılanan araçları bildirir.
[`tool_composition.py`](../../deeptutor/agents/_shared/tool_composition.py),
bağlama bayraklarının ve her zaman kullanılabilir çalışma alanı araçlarının
sahibidir. Yeteneğe ait solve, mastery ve diğer özelleşmiş araçlar kendi
etkinleştirme sözleşmelerini izler. Partner izin/engel yüzeyi erişimi daha da
daraltabilir.

Hesap izinleri, çalışma alanı kaynak politikaları, modül seçimi ve yetenek
etkinleştirmesinin tümü, keşif ve gönderim (dispatch) sırasında geçerli kalmalıdır.
Bir kullanıcı arayüzündeki veya manifest'teki araç adı bu kontrolleri
atlatmamalıdır. MCP/CLI ertelenmiş keşfi, paralel bir kayıt defteri kurmak yerine
mevcut yükleyiciyi kullanmalıdır.

## Yerleşik bir araç veya yetenek ekleme ya da değiştirme

1. Tiplenmiş işlemi veya yeteneği sahibi olan modülde uygulayın. İsteğe bağlı
   kütüphaneleri yalnızca meta veri içeren içe aktarmaların dışında tutun.
2. Araç spesifikasyonunu veya yetenek bildirimini, takma adları ve sahibi olan
   modül manifest'ini güncelleyin. Tembel araç tanımlayıcıları
   [`builtin_specs.py`](../../deeptutor/tools/builtin_specs.py) dosyasındadır.
3. Bağlama mantığını mevcut kompozisyon/etkinleştirme sahibine koyun. Bir aracın
   kullanıcı tarafından açılıp kapatılabilir mi, bağlama göre kapılanan mı yoksa
   yeteneğe ait mi olduğuna açıkça karar verin.
4. Gerektiğinde istek doğrulamasını ve çevrilmiş istemleri güncelleyin. Yetenek
   istemleri [`capabilities/prompts/`](../../deeptutor/capabilities/prompts/)
   altındadır; bazı ajan uygulamaları kendi dizinlerinde ek istemlere sahiptir.
5. Meta veri/uygulama uyumunu, eksik modül davranışını, yetkili kaynak kapsamını,
   hata ve iptali ve herkese açık sonuç zarfını test edin. Şema yeniden üretimi
   ve daha geniş kontroller için [Test](TESTING.md) belgesini izleyin.

Bağımsız olarak dağıtılan bir paket için yerleşik kaydı değiştirmek yerine
[eklenti sözleşmesini](PLUGINS.md) ve
[Learning Echo örneğini](examples/learning_echo/README.md) kullanın. Okuma
araç çubuğu eylemlerinin ayrı bir
[Reading extension protocol](READING_EXTENSIONS.md) belgesi vardır.

## Beklenmedik bir araç çağrısını tanılama

Etkin modül durumunu, yeteneği, seçili kaynakları, kullanıcının araç seçimini ve
çalışma alanı politikalarını, model isteğine gerçekte kabul edilen şemalarla
karşılaştırın. Ardından gönderimi ve dönen kanıtı inceleyin. Seçili bir bilgi
tabanı (KB), getirmenin çalıştığını kanıtlamaz; getirilen bir URL, piksellerin
modele ulaştığını kanıtlamaz. Bkz. [kaynak görselleri](SOURCE_VISUALS.md) ve
[yanıt kalitesi tanılaması](REASONING_SAFETY_CHECKLIST.md).
