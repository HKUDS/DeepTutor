# Olaylar, kalıcı yeniden oynatma ve dizinleme ilerlemesi

[El kitabı](README.md) · [Mimari](ARCHITECTURE.md) · [Dizinleme kurtarma](INDEXING_RECOVERY.md)

Farklı olay sistemlerinin kalıcılık garantileri farklıdır. Teşhis edilen
işlemden başlayın; süreç içi bir bildirim, kalıcı bir tur günlüğü değildir.

| Akış | Ana sahipler | Neye bakılmalı |
| --- | --- | --- |
| Model turu | [Uygulama servisi](../../deeptutor/app/service.py), [tur çalışma zamanı](../../deeptutor/services/session/turn_runtime.py), [StreamBus](../../deeptutor/runtime/stream_bus.py) | Gönderim kimliği, kalıcılaştırılmış sıra, yeniden oynatma imleci, sonlandırıcı olay |
| Çok worker'lı koordinasyon | [Coordinator](../../deeptutor/runtime/coordination/) | Lease sahibi, fencing, iptal bildirimi, kurtarma |
| Bilgi alımı | [İlerleme izleyicisi](../../deeptutor/knowledge/progress_tracker.py), [dizinleme günlüğü](../../deeptutor/knowledge/indexing_run.py) | Görev kimliği, kaynak sonuçları, yayımlama durumu, son etkinlik |
| Bilgi arayüzü aktarımı | [İlerleme portları](../../deeptutor/knowledge/progress_events.py), [broadcaster](../../deeptutor/api/utils/progress_broadcaster.py), [görev akışı](../../deeptutor/api/utils/task_log_stream.py) | Anlık görüntü, WebSocket ilerlemesi, SSE günlükleri/sonlanma durumu |
| Süreç bildirimleri | [EventBus](../../deeptutor/events/event_bus.py) | Mevcut yayıncılar/aboneler; süreç ömrü |

## Tur yaşam döngüsü

Uygulama servisi, kabul ve yürütmeyi paylaşılan oturum deposu ve çalışma
zamanı üzerinden koordine eder. Her yürütmenin tur başına bir akış veri yolu
vardır; olaylar, bağdaştırıcılar tüketicilere iletmeden önce kalıcılık/yeniden
oynatma yoluna girmelidir. Tarayıcı bağlantısının kopması tek başına turun
başarısız olduğunu kanıtlamaz ve ikinci bir yürütmeyi meşru kılmaz. Kurtarma,
etkin bir lease ile kaybolmuş bir worker'ı birbirinden ayırt etmeli ve
sonlanma durumunu korumalıdır.

Akışı değiştirirken yinelenen gönderimi, kısmi çıktıdan sonra yeniden
bağlanmayı, sonlandırıcı olaydan sonra yeniden oynatmayı, iptali ve worker
kaybını test edin. Varış sırasını veya işlenmiş metni kalıcı gerçek kaynağı
saymak yerine olay kimliklerini/sıralarını ve mevcut projeksiyon kurallarını
koruyun. Protokol tipleri [`core/stream.py`](../../deeptutor/core/stream.py)
içinde bulunur; ön yüz, [`web/contracts/`](../../web/contracts/) altındaki
sözleşmeleri kullanır.

Tek bir worker bellek koordinatörünü kullanabilir. Birden fazla arka uç
worker'ı için Redis koordinasyonu gerekir; bu, `system.backend_workers` ve
`integrations.turn_coordination` üzerinden yapılandırılır.
[Ayar doğrulayıcısı](../../deeptutor/runtime/coordination/settings.py), bellek
koordinatörüyle birden fazla worker'ı ve URL olmadan Redis'i reddeder. Redis,
koordinasyon/bildirim katmanıdır; oturum deposunun yerini almaz.
`deeptutor doctor runtime --format json` çalışma zamanı tanılamalarını raporlar.

## Bilgi tabanı ilerlemesi

`ProgressTracker`, anlık görüntüleri kalıcılaştırır ve enjekte edilen ilerleme
portları üzerinden olay yayar. API, WebSocket/SSE portlarını kurar; alan kodu
ilerlemeyi bildirmek için FastAPI'yi içe aktarmamalıdır. CLI/SDK yürütmesi de
bir tarayıcı broadcaster'ı olmadan ilerlemeyi kalıcılaştırabilir.

Bilgi router'ı bir ilerleme WebSocket'i ve görev günlüğü SSE akışı sunar.
[`useKnowledgeProgress`](../../web/hooks/useKnowledgeProgress.ts) ikisini
birleştirir, beklenen görevi izler ve sonlanma durumunu uzlaştırır. Yeniden
bağlanırken veya bir anlık görüntü uygularken çalışma alanı kapsamını ve görev
kimliğini koruyun. Günlükler ve yüzde tahminleri gözlemdir; bir dizinin
yayımlandığının kanıtı değildir.

[Dizinleme günlüğü](INDEXING_RECOVERY.md); kaynak düzeyindeki başarıyı,
başarısızlığı ve yarıda kalan işi kaydeder. Tamamlanma, kalıcılaştırılmış
yayımlamayla uyumlu olmalıdır; bir ayrıştırıcının son partiye ulaşması yeterli
değildir. Yeniden oluşturmalar, sorgulanabilir bir sürümü kısmi bir adayla
değiştirmemelidir. Ayrıştırma kontrol noktaları ve kesin kaynak konumlayıcıları
için ayrıca [kaynak görselleri](SOURCE_VISUALS.md) belgesini okuyun.

## Hata ayıklama sırası

1. Hesabı, çalışma alanını, oturum/tur veya KB/görev kimliğini ve zaman aralığını belirleyin.
2. Önce kalıcı durumu, ardından coordinator/worker'ı ve aktarımı kontrol edin.
3. Tarayıcının imleç/görev kimliğini sunucunun kalıcılaştırılmış durumuyla karşılaştırın.
4. Kopan bağlantıları, eski anlık görüntüleri ve yinelenen çerçeveleri fixture'larla yeniden üretin. İlerlemeyi başarı alanlarını elle üzerine yazarak onarmayın.
5. Sonlanma durumunu yalnızca özgün tarayıcı bağlantısı canlıyken değil, yeniden açtıktan sonra da doğrulayın.

İlgili test takımları arasında [uygulama testleri](../../tests/app/),
[koordinasyon testleri](../../tests/runtime/coordination/),
[bilgi testleri](../../tests/knowledge/) ve
[bilgi ilerlemesi WebSocket testleri](../../tests/api/test_knowledge_progress_ws.py)
bulunur.
