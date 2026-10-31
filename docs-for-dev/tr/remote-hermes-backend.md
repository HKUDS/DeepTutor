# Uzak Hermes Agent backend'i

[El kitabı](README.md) · [İlgili kılavuz](ARCHITECTURE.md)

DeepTutor Connected Agents, DeepTutor konteynerine bir Hermes CLI kurmadan bir Hermes Agent ağ geçidini çağırabilir. Backend türü `hermes_remote` olup görünen adı **Hermes Agent (remote)** şeklindedir.

## Yapılandırma

Backend'e özgü ayarlar, normal `subagent.json` ayar belgesindeki `backends.hermes_remote` altında bulunur:

- `enabled`: sohbetin bu backend'e görev devredip devredemeyeceği.
- `base_url`: ağ geçidi kökü, örneğin `http://hermes-uni:8642`.
- `api_key_env`: ağ geçidi bearer belirtecini içeren ortam değişkeninin adı. Varsayılan değeri `DEEPTUTOR_HERMES_REMOTE_API_KEY`'dir.
- `profile`: bilgilendirme amaçlı dağıtım/profil etiketi; bir kimlik bilgisi değildir ve URL oluşturmak için kullanılmaz.
- `model`, `effort`, `system_prompt`, `auto_approve`: yerel backend'lerle paylaşılan çalıştırma denetimleri.
- `idle_timeout_seconds`: SSE çerçeveleri arasındaki en uzun boşta kalma aralığı (varsayılan `600`). Ağ geçidinden gelen keepalive iletileri bu bekçi zamanlayıcısını sıfırlar.

API anahtarı yalnızca ortam değişkeninde tutulur. Satır içi bir ayar alanı olarak asla kabul edilmez, kalıcı olarak saklanmaz ve `GET /api/subagents/settings` tarafından döndürülmez.
Ağ geçidi URL'si, kimlik bilgisi, sorgu metni veya parça (fragment) içermeyen bir HTTP(S) adresi olmalıdır.
İsteğe bağlı bir `/p/<profile>` öneki, Hermes çoklu profil yönlendirmesini destekler.
Yönlendirmeler asla izlenmez.

## HTTP sözleşmesi

Adaptör, açık bağlantı/okuma/yazma/havuz zaman aşımlarıyla kimliği doğrulanmış bearer istekleri (`Authorization: Bearer ...`) kullanır. Uç noktalar ve makine tarafından okunabilir özellik sözleşmesi [Hermes API Server kılavuzunda](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/) belgelenmiştir.

1. `GET /v1/capabilities` kullanılabilirliği algılar ve yapılandırılan ağ geçidinin çalıştırma gönderimini, olay akışını, durdurmayı, onay yanıtlarını ve oturum kaynaklarını duyurduğunu doğrular. Algılama; `not_configured`, `key_missing`, `unreachable`, `unauthorized` ve `incompatible` ayrıntılarını ayrı ayrı bildirir.
2. `POST /v1/runs` bir çalıştırma başlatır. İstek, kullanıcı istemi için `input`, isteğe bağlı ilk oturum sistem talimatı için `instructions`, yapılandırılmışsa `model`, yapılandırılmışsa `model_options.reasoning_effort` ve devam ediliyorsa `session_id` kullanır. Sunucu, `{ "run_id": "...", "status": "started" }` ile HTTP 202 döndürür. Yeni bir çalıştırma kendi çalıştırma kimliğini oturum kimliği olarak kullanır; devam ettirilen bir çalıştırma, sağlanan oturum kimliğini korur.
   Devam ettirilen bir çalıştırmadan önce adaptör `GET /api/sessions/{session_id}/messages` isteğini getirir. Yalnızca boş olmayan kullanıcı/asistan satırlarını tutar, araç satırlarını hariç tutar ve en fazla son 40 satırı `conversation_history` olarak gönderir. 404, oturumun artık mevcut olmadığı anlamına gelir: eski oturum kimliği ve başlıklar bırakılır, çalıştırma geçmiş olmadan yeniden başlar ve `system_prompt` tekrar uygulanır.
3. `GET /v1/runs/{run_id}/events` bir SSE akışıdır. Çerçeveler, bir `data:` satırında JSON içerir. Adaptör şu olay nesnelerini tüketir: `message.delta` (`delta`), `tool.started` (`tool`, `preview`), `tool.completed` (`tool`, `error`), `reasoning.available` (`text`), `approval.request`, `run.completed` (`output`), `run.failed` (`error`) ve `run.cancelled`. Araç yaşam döngüsü olayları araç/araç sonucu satırlarına dönüşür; yanıt delta'ları `hermes_remote:final` birleştirme kimliği altında kümülatif metne dönüşür; diğer yaşam döngüsü olayları günlük/hata satırlarına dönüşür. Ağ geçidi araç/akıl yürütme, metin/tamamlanma ve onay olaylarını aynı akış üzerinden yayar.
4. `POST /v1/runs/{run_id}/approval` bekleyen bir onayı çözer. Gövde, otomatik onay için `{ "choice": "once" }`, `auto_approve` false olduğunda ise `{ "choice": "deny" }` biçimindedir. Başarısız bir onay yanıtı yüzeye çıkarılır ve çalıştırma süresiz beklemek yerine durdurulur.
5. `POST /v1/runs/{run_id}/stop` bir çalıştırmayı keser. İptal, bu isteği korumalı ve sınırlı bir temizlik penceresiyle gönderir, ardından iptali yeniden yükseltir; bir SSE boşta kalma zaman aşımı ise bu isteği gönderir ve hata döndürür.

Oturum sürekliliği hem ağ geçidinin belgelenmiş `X-Hermes-Session-Id` başlığını hem de `session_id` istek alanını kullanır. Adaptör ayrıca uyumluluk amaçlı `X-Hermes-Session` başlığını da gönderir. Özel `system_prompt`, yeni bir oturumda veya geçmiş sorgusu oturumun artık mevcut olmadığını bildirdiğinde (404) gönderilir. Her istek, DeepTutor Connected Agents'ı tanımlayan ve ağ geçidi ajanına DeepTutor'a geri devretmek yerine doğrudan yanıt vermesini söyleyen sabit `CONSULT_ORIGIN_INSTRUCTION` özyineleme korumasını taşır.

`/v1/runs` API'sinde görsel yükleme alanı yoktur. Bu nedenle ekler ve bunların DeepTutor yerel yolları uzak ağ geçidine gönderilmez.

## Yalıtım ve güvenlik

Bu backend, Hermes ağ geçidini DeepTutor sürecinin/konteynerinin dışında tutar: araçlar DeepTutor'da değil, ağ geçidi ana makinesinde çalışır. Her DeepTutor sohbetini, kendisine döndürülen oturum kimliğiyle sınırlandırın; oturum kimliklerini kullanıcılar veya sohbetler arasında paylaşmayın. `API_SERVER_KEY` (ağ geçidinin sunucu tarafı gizli anahtarı) ile `DEEPTUTOR_HERMES_REMOTE_API_KEY` (DeepTutor tarafı ortam değişkeni adının değeri) değerlerini ayar dosyalarından, günlüklerden, olay metninden ve ön yüz yüklerinden uzak tutun.

Akış, adaptörün sunduğu yapılandırılmış SSE yaşam döngüsü dışında sessizdir. `POST /v1/runs` isteğini yoklamaz veya yeniden denemez; çağıran tarafın iptali ya da boşta kalma bekçisi her zaman sınırlı bir durdurma denemesi yapar.

## Uygulama ve doğrulama

- [deeptutor/services/subagent/hermes_remote.py](../../deeptutor/services/subagent/hermes_remote.py)
- [deeptutor/services/subagent/hermes_remote_client.py](../../deeptutor/services/subagent/hermes_remote_client.py)
- [deeptutor/services/subagent/hermes_remote_events.py](../../deeptutor/services/subagent/hermes_remote_events.py)
- [tests/services/test_hermes_remote_backend.py](../../tests/services/test_hermes_remote_backend.py)
