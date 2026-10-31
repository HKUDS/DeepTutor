# Çalışma zamanı tasarımı: etkinleştirme, worker'lar ve model geçmişi

[El kitabı](README.md) · [Mimari](ARCHITECTURE.md) · [Olaylar](EVENTS_AND_PROGRESS.md)

Bu sayfa, önceki tasarım notlarından uygulanmış kararları saklar. Güncel
sınırları anlatır; geçmiş bellek ölçümleri ve tek makinede yapılan test sayıları
performans garantisi değildir.

## Tembel etkinleştirme

Araç/yetenek katalogları içe aktarma açısından hafif tanımlayıcılar kullanır.
Kayıt defteri incelemesi kullanılmayan sağlayıcıları, ayrıştırıcıları veya
isteğe bağlı modülleri hevesle içe aktarmamalıdır. Kayıt defterleri
uygulamaları talep üzerine yükler; modül seçimi ve eklenti onayı etkinleştirme
anında da geçerli kalır. Uyumluluk dışa aktarımları, mevcut içe aktarma yollarını
korumak için tembel sarmalayıcılar kullanabilir.

Ön yüz de benzer şekilde ayar düzenleyicilerinin yüklenmesini erteler. Yükleme
mantığını değiştirirken çapa/gezinme etkinleştirmesini ve kimlik doğrulama
single-flight davranışını koruyun. Yalnızca sıcak süreç zamanlamasıyla değil,
içe aktarma sınırı testleri ve ön yüz rota bütçeleriyle doğrulayın. Kaynak
sahipleri: [kayıt defterleri](../../deeptutor/runtime/registry/),
[modül birleştirme](../../deeptutor/modules/) ve
[ayarlar](../../web/features/settings/).

## Kısa ömürlü ayrıştırma worker'ları

Ağır eşzamanlı çıkarma işlemleri, bir iş parçacığında çalıştırılsa bile uzun
ömürlü bir API sürecinde yerel kütüphane belleğini tutabilir.
[Yalıtılmış worker sınırı](../../deeptutor/runtime/isolated_worker.py), dahili
içe aktarılabilir bir çağrılabilir ve özel geçici girdi/sonuç dosyaları
kullanarak [`worker_process.py`](../../deeptutor/runtime/worker_process.py) üzerinden
kısa ömürlü bir yorumlayıcı başlatır.

Bu, güvenilir dahili IPC'dir. Serileştirilmiş Python nesneleri, güvenilmeyen
yükleme veya ağ girdisi için bir API değildir. İstemciler rastgele bir
çağrılabilir seçemez. Alt süreç sınırı, çıkışta belleğini serbest bırakır; ancak
güvenilmeyen kod için tek başına bir işletim sistemi güvenlik sanal alanı
(sandbox) değildir.

Zaman aşımı ve iptal, dönmeden önce süreç ağacını sonlandırmalı ve birleştirmelidir
(join). Eşzamanlılık `DEEPTUTOR_ISOLATED_WORKERS` ile sınırlandırılır
(varsayılan iki); çağrı noktaları varsayılan zaman aşımını geçersiz kılabilir.
Platforma özgü temizliği ve sonuç/hata geri yüklemesini
[worker testleri](../../tests/runtime/test_isolated_worker.py) kapsamında tutun.
Ayrıştırıcı hataları, boş ama başarılı bir çıkarmadan ayırt edilebilir kalmalıdır.

## Özel model geçmişi

Görüntülenen mesajlar ve sağlayıcıya hazır model geçmişi farklı amaçlara hizmet
eder. [`model_history.py`](../../deeptutor/services/session/model_history.py),
hazırlanmış girdiyi, anlık görüntüleri, model/araç mesajlarını, yeniden oynatma
meta verilerini ve istek parmak izlerini içeren sürümlü, özel bir `model_turn`
saklar. Herkese açık oturum yanıtları ve dışa aktarımlar bunu gizler. Geçerli
model meta verisi olmayan eski satırlar, görüntüleme geçmişi yedeğini korur.

Paylaşılan döngü, değişen çalışma zamanı olgularını adlandırılmış anlık görüntüler
olarak eklerken kalıcı talimatları sabit tutar. Bir anlık görüntüyü değiştirmek
yalnızca o bölümü değiştirir; kaynak materyali sistem politikası olarak yeniden
yorumlamamalıdır. Araç kullanılabilirliği, çalışma alanı yolları ve kaynak
izinleri hâlâ kendi olağan yetkili kaynaklarından gelir.

Saklama/sıkıştırma, bir model turunun araç çağrılarını ve sonuçlarını birlikte
tutmalıdır. Yarıda kesilen araçlar, uydurma başarılı bir yanıt yerine açık bir
kullanılamaz-sonuç yanıtı alır. Rota değişiklikleri, herkese açık kanıtı
korurken uyumsuz özel sağlayıcı yeniden oynatma alanlarını kaldırır.
Değişiklikler saklanan konuşma içeriğini ve hesap/çalışma alanı yalıtımını
korumalıdır.

## Önbellek kanıtı

İstek önbelleği tanılamaları, kanonik istek parmak izlerini ve değişmeyen önek
mesajlarını karşılaştırır. Bir sağlayıcının önbelleğe alınmış token sunduğunu
kanıtlamazlar. Faturalandırılan/önbellek isabeti davranışının kanıtı gerçek
sağlayıcı kullanım sayaçlarıdır; rota değişiklikleri, tahliye, araç değişiklikleri
ve sıkıştırma yeniden kullanımı geçersiz kılabilir.

[Model geçmişi regresyon testleri](../../tests/services/session/test_model_history.py)
ve [istek önbelleği testleri](../../tests/services/llm/test_request_cache.py) ile
başlayın. İsteğe bağlı
[istem önbelleği entegrasyon testi](../../tests/integration/test_prompt_cache.py),
yapılandırılmış gerçek sağlayıcı ile sentetik girdiler kullanır:

```bash
DEEPTUTOR_CACHE_E2E=1 python -m pytest tests/integration/test_prompt_cache.py -q
```

Bu, sağlayıcı kullanım maliyeti doğurabilir. Başarılı bir sentetik önbellek
probu, üretim gecikmesi veya maliyet kıyaslaması değildir; aşamaya özgü
işlem hatlarının paylaşılan sohbet döngüsünden farklı geçmiş sözleşmeleri olabilir.
