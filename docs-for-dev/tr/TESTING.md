# Test ve doğrulama

[El kitabı](README.md) · [Geliştirme](DEVELOPMENT.md) · [Modüller](MODULES.md#doğrulama)

Deponun yapılandırılmış araçlarını ve [Ajan kurulumu](AGENT_SETUP.md)
belgesindeki ortamı kullanın. Geliştirme sırasında hedefe yönelik kontroller,
yayımlamadan önce ise etkilenen proje geçitleri çalıştırın. Yalnızca
dokümantasyon içeren bir değişiklik ücretli model çağrıları veya tam bir
render iş yükü gerektirmez.

## Değişikliğe göre kontrol seçimi

| Değişiklik | Asgari yararlı kanıt |
| --- | --- |
| Dokümantasyon ve CLI örnekleri | Bağlantılar/çapalar, CLI dokümantasyon sözleşmeleri, komut yardımı, eskimiş yol olmaması |
| Python alan mantığı | Odaklı pytest ile yeniden üretim; Ruff; ilgili içe aktarma sınırları |
| API veya tur olayları | İstek/yetkilendirme testleri, üretilmiş sözleşme kontrolü, kalıcılık/yeniden oynatma testleri, tüketici testleri |
| Ön yüz davranışı | Tür denetimi, odaklı Node/Vitest testi, bağımlılık kontrolü; etkileşim/yerleşim için tarayıcıda doğrulama |
| Modül sahipliği/bağımlılıkları | Üretilmiş requirements dosyaları, modül yalıtımı, wheel yaşam döngüsü smoke testi |
| Eklenti worker'ı veya paketlenmiş sayfa | Manifest, çalışma zamanı/yaşam döngüsü ve API testleri, referans örnek wheel |
| Ayrıştırma/alt süreç kodu | Gerçek alt süreçte başarı/hata/zaman aşımı/iptal; ilgili platform kontrolleri |
| Sağlayıcı/model entegrasyonu | Sahte (mock) sözleşme testleri ve gerektiğinde açıkça yapılandırılmış gerçek sağlayıcı probu |

## Python

```bash
python -m pytest tests/cli/test_docs_contract.py tests/scripts/test_docker_compose.py
python -m pytest tests/app tests/runtime/coordination
python -m pytest tests/plugins tests/api/test_plugins_router.py
python -m ruff check .
python -m ruff format --check .
lint-imports
python scripts/check_architecture.py
python scripts/sync_module_requirements.py --check
python scripts/check_repo_hygiene.py
```

Bunlar ayrı giriş noktalarıdır; ilk komutun tüm değişiklikleri kapsadığını
varsaymak yerine ilgili paketleri seçin. Tam Python paketi
`python -m pytest tests deeptutor/learning/tests` komutudur. Bazı entegrasyon
senaryoları Redis, isteğe bağlı motorlar veya platforma özgü çalıştırılabilir
dosyalar gibi fixture'lar gerektirir. Atlama koşullarını okuyun ve atlanan
kontrolleri doğru biçimde raporlayın.

`check_repo_hygiene.py` izlenen yolları denetler. Daha katı olan
`check_workspace_hygiene.py` ayrıca çalışma kopyasının tamamen temiz olmasını
gerektirir; bu yüzden amaçlanan düzenlemeleri test hatası saymak yerine onu
commit'ten sonra çalıştırın.

## Web ve üretilmiş sözleşmeler

`web/` dizininden:

```bash
npm run typecheck
npm run architecture:check
npm run test:node
npm run test:unit
npm run lint
npm run i18n:check
npm run contracts:check
```

`npm run check:fast` yukarıdaki deterministik kontrolleri çalıştırır;
`npm run check` ise üretim derlemesini ve rota bütçelerini ekler. Arka uç
şemalarını değiştirdikten sonra `npm run contracts:generate` komutunu kullanın,
ardından üretilen farkı inceleyip commit'leyin. Üreteç
[`web/contracts/`](../../web/contracts/) dizininin sahibidir ve
[Python dışa aktarma betiğini](../../scripts/export_frontend_contracts.py) çağırır.

Render edilen bileşen testleri Vitest ve Testing Library kullanır. Node
testleri saf sözleşmeleri ve durum mantığını kapsar. Playwright
`npm run audit` komutu `WEB_BASE_URL` adresinde çalışan bir ön yüz bekler;
kritik ve çoklu worker projelerinin ayrı fixture gereksinimleri
[`playwright.config.ts`](../../web/playwright.config.ts) dosyasındadır. Tarayıcı
üzerinde değişiklik yapan işlemleri bir öğrenenin verisinin tek kopyası üzerinde
çalıştırmayın.

## Modüller, motorlar ve isteğe bağlı entegrasyon

Tek kullanımlık wheel kurulumu, kaldırma/yeniden kurma ve korunan veri
kontrolleri için [Modüller → Doğrulama](MODULES.md#doğrulama) bölümünü izleyin.
Paket kaldırmayı test etmek için geliştirme yorumlayıcısını kullanmayın.

Deneysel TypeScript motorunun
[`packages/chat-engine/`](../../packages/chat-engine/) altında kendi `npm test`
komutu vardır; buna ek olarak Python köprüsü ve uygulama uyumluluk testleri
bulunur. Kanonik matris [`tests.yml`](../../.github/workflows/tests.yml) ve
[`modules.yml`](../../.github/workflows/modules.yml) dosyalarındadır.

`deeptutor doctor --online` gerçek bir model isteği yapar. İstem önbelleği
(prompt-cache), video render ve çoklu worker kabul testleri açıkça etkinleştirme
değişkenleri gerektirebilir. Gerçek ortamı ve yapılan doğrulamayı belirtin;
geçmiş test sayıları ve sahte (mock) bir sağlayıcı, güncel üretim davranışını
kanıtlamaz.

## Bir dokümantasyon değişikliğini inceleme

Göreli bağlantıları depo kökünden değil, her dosyanın kendi konumundan kontrol
edin. Bir kılavuzu taşırken README çevirilerini (`assets/README/`, `docs-for-dev/tr/`), CLI yardımını, kullanıcı
arayüzü kurulum istemlerini ve test fixture'larını arayın. Kaynak
bağlantılarını kırılgan satır numaralarından uzak tutun. Komutları ve
varsayılanları doğrulamak için kurulu CLI'ın `--help` çıktısını ve yetkili
manifest/ayarları kullanın. Yerel artifact'leri ve gizli bilgileri commit'in
dışında tutun.
