# İsteğe bağlı istek taraması (fastapi-guard)

[El Kitabı](README.md) · [İlgili kılavuz](CONTAINERIZATION.md)

DeepTutor, HTTP isteklerini arka uç içinde [fastapi-guard](https://github.com/Guard-Core/fastapi-guard) ile tarayabilir. Bu özellik **varsayılan olarak kapalıdır**. Kapalıyken paket hiç içe aktarılmaz ve middleware yığını değişmez. Her yeni ayarda olduğu gibi `system.json`, bir sonraki yüklemede varsayılan değerleriyle birlikte devre dışı `security_guard` bloğunu alır; bozuk bir blok ise varsayılanlarla değiştirilir.

Guard bir uygulama katmanı denetimidir. Uçtaki bir ters proxy, WAF veya güvenlik duvarını tamamlar ve arka uç portuna bunlar olmadan erişildiğinde de (örneğin yayımlanmış bir `:8001`, bir LAN üzerinde `deeptutor serve` veya bir tünel) çalışmaya devam eder.

## Ne yapar

Her HTTP isteği için aşağıdaki sırayla şunları denetler:

- **IP listeleri**: isteğe bağlı bir izin listesi (yalnızca listelenen adresler geçer) ve isteğe bağlı bir engelleme listesi.
- **Hız sınırı**: istemci adresi başına kayan pencere; varsayılan olarak 60 saniyede 300 istek.
- **Yasak listesi**: tekrarlanan saldırı kalıbı eşleşmeleri tetikleyen bir adres, bir süre engellenir.
- URL yolu, sorgu dizesi ve üst bilgilerin **saldırı kalıbı taraması** (XSS, SQL injection, path traversal ve benzerleri). Eşleşme `400` döndürür. `ssrf` kategorisi kapalıdır; çünkü tarayıcılar sayfa adresini `Referer` olarak gönderir ve guard-core 4.4.0 bu adresteki localhost ve LAN adreslerini işaretler. Bu nedenle SSRF kalıpları taranmaz; motor düzeltmesi yayımlandığında yeniden ele alınacaktır.

Reddedilen istekler `429` (hız sınırı) veya `403` (IP listeleri, yasak) döndürür. Guard, `CORSMiddleware` içinde yer alır; bu yüzden bu yanıtlar yine CORS üst bilgilerini taşır ve tarayıcı, opak bir CORS hatası yerine gerçek durumu gösterir.

## Ne yapmaz

- İstek gövdelerini asla okumaz. İstemler, belgeler ve sohbet mesajları serbest metindir; bu nedenle gövde taraması kapalıdır (`detection_scan_body=False`).
- WebSocket el sıkışmalarını (`/ws`) taramaz, yalnızca HTTP isteklerini tarar.
- Redis kullanmaz. Sayaçlar her arka uç sürecinin içinde tutulur; bu yüzden `backend_workers` 1'den büyükse etkin sınır, `rate_limit` değerinin worker sayısıyla çarpımına kadar çıkabilir.
- Güvenlik üst bilgisi eklemez, CORS'u yönetmez ve telemetri göndermez (`security_headers`, `enable_cors` ve `enable_agent` kapalıdır).

fastapi-guard 8.1.1 / guard-core 4.4.0 sürümleri itibarıyla bilinmesi gereken iki motor davranışı (sonraki motor sürümleri bunları değiştirebilir): motorun varsayılan `exclude_paths` listesindeki yollar (`/docs`, `/redoc`, `/openapi.json`, `/openapi.yaml`, `/favicon.ico`, `/static`) yalnızca saldırı kalıbı taramasını atlar, hız sınırı ve IP listeleri bunlara yine uygulanır; izin listesindeki bir adres ise hem saldırı kalıbı taramasını hem de hız sınırını atlar.

## Etkinleştirme

1. Sunucuya sahip ortama isteğe bağlı guard bağımlılıklarını kurun:

   ```bash
   # Source checkout:
   python scripts/install_extras.py guard
   # Wheel environment with the server already installed:
   python -m pip install "deeptutor[guard]"
   ```

   Docker'da, diğer ekstralarda olduğu gibi hizmette `DEEPTUTOR_EXTRAS: "guard"` ayarlayın ([CONTAINERIZATION.md](CONTAINERIZATION.md) dosyasına bakın).

2. `data/user/settings/system.json` içinde etkinleştirin:

   ```json
   {
     "security_guard": {
       "enabled": true,
       "rate_limit": 300,
       "rate_limit_window": 60,
       "trusted_proxies": ["127.0.0.1", "::1"],
       "exempt_ips": ["127.0.0.1", "::1"],
       "whitelist": [],
       "blacklist": []
     }
   }
   ```

   Docker dışında aynı anahtarlar süreç ortam değişkeni geçersiz kılmaları olarak da ayarlanabilir: `DEEPTUTOR_GUARD_ENABLED`, `DEEPTUTOR_GUARD_RATE_LIMIT`, `DEEPTUTOR_GUARD_RATE_LIMIT_WINDOW`, `DEEPTUTOR_GUARD_TRUSTED_PROXIES`, `DEEPTUTOR_GUARD_EXEMPT_IPS`, `DEEPTUTOR_GUARD_WHITELIST` ve `DEEPTUTOR_GUARD_BLACKLIST` (virgülle ayrılmış IP'ler veya CIDR aralıkları). Docker giriş noktası süreç ortam değişkeni geçersiz kılmalarını yok sayar; bu nedenle konteynerde `system.json` kullanın.

3. Arka ucu yeniden başlatın.

`enabled` true ise ve `fastapi-guard` kurulu değilse arka uç başlamayı reddeder ve nasıl kurulacağını yazdırır. Geçersiz IP veya CIDR girdileri de başlangıçta hata verir.

### Hız sınırını boyutlandırma

Sınır, ön yüzün arka plan yoklaması da dahil olmak üzere (birkaç panel her 1 ila 5 saniyede bir yoklama yapar) bir istemci adresinden gelen **her** HTTP isteğini sayar. 60 saniyede 300 istek, birkaç açık panele yer bırakır; oysa fastapi-guard 8.1.1'in hiçbir şey yapılandırılmadığında kullandığı 60 saniyede 10 istek, normal kullanımda bile devreye girerdi. Next.js ön yüzü statik varlıklarını kendisi sunar; bu nedenle bu istekler arka uca ulaşmaz ve sayılmaz.

## İstemci adresi ve proxy'ler

Guard, bir istemciyi isteğin soket eşiyle (socket peer) tanımlar. `X-Forwarded-For` değerine yalnızca eş `trusted_proxies` içinde listeliyse (varsayılan: yalnızca loopback) güvenir. Başka herhangi bir eşten gelen isteğin `X-Forwarded-For` değeri yok sayılır.

Uvicorn da uygulama eşi görmeden önce eşi `X-Forwarded-For` (ve `FORWARDED_ALLOW_IPS`) değerinden yeniden yazabilir; bu, bir istemcinin kendi kimliğini seçmesine izin verirdi. Her DeepTutor başlatma yolu zaten `proxy_headers=False` / `--no-proxy-headers` geçirir (`deeptutor/api/run_server.py`, `deeptutor_cli/main.py`, `deeptutor/runtime/launcher.py`, her iki `Dockerfile` başlatma satırı); böylece guard gerçek eşi görür. `tests/api/test_security_guard.py`, bunu `uvicorn.Config(...).load()` üzerinden denetler.

Arka ucu kendiniz başlatıyorsanız bayrağı koruyun:

```bash
python -m uvicorn deeptutor.api.main:app --host 0.0.0.0 --port 8001 --no-proxy-headers
```

Arka ucun önünde bir ters proxy varsa adresini `trusted_proxies` içine ekleyin; aksi halde her istemci proxy gibi görünür. Guard, bu nedenle özel bir adresi yasakladığında uyarı verir.

Çift yığınlı (dual-stack) bind'ler: guard-core 4.4.0 ile IPv4 eşlemeli biçimde bildirilen bir eş (`::ffff:a.b.c.d`, çift yığınlı bir `::` bind'inde olduğu gibi) IPv4 `trusted_proxies` girdileriyle eşleştirilmez; bu yüzden bir ters proxy'nin `X-Forwarded-For` değeri yok sayılır ve tüm istemcileri proxy'nin kovasını paylaşır. Varsayılan başlatma yolları `0.0.0.0` adresine bind eder ve bundan etkilenmez. `::` adresine bind ederseniz her proxy'nin eşlemeli biçimini de listeleyin; örneğin `["10.0.0.0/8", "::ffff:10.0.0.0/104"]` (guard-core 4.4.0 ile denetlendi ve bir testle kapsanıyor). Sonraki guard-core sürümlerinde buna gerek kalmayabilir.

**Paketle gelen ön yüz.** Next.js proxy'si (`web/proxy.ts`), tarayıcı isteklerinden `X-Forwarded-For` ve diğer iletim üst bilgilerini siler (`web/lib/backend-forward.ts`) ve tarayıcının adresini eklemez. Arka uca bu yolla ulaşan istekler, iletim üst bilgisi olmadan, hep ön yüzün kendi adresinden (varsayılan düzende loopback) gelir. Tek bir paylaşılan sınır tüm kullanıcıları birlikte kısıtlardı; bu nedenle `exempt_ips` (varsayılan `127.0.0.1` ve `::1`) bu adresi hız sınırından muaf tutar. Dolayısıyla ön yüz üzerinden gelen istekler saldırı kalıpları ve engelleme listesi için taranır, ancak hız sınırına tabi tutulmaz. İstemci başına sınırlar, arka uca doğrudan ulaşan veya `X-Forwarded-For` ayarlayan ve `trusted_proxies` içinde listelenen bir ters proxy üzerinden ulaşan isteklere uygulanır (`exempt_ips` loopback içerdiğinde, `X-Forwarded-For` taşıyan bir loopback isteği iletilen istemci olarak sınırlanır). `exempt_ips` yalnızca hız sınırını atlar: engelleme listesi, yasaklar ve saldırı kalıbı taraması listelenen adreslere yine uygulanır. Guard loopback adreslerini yasaklamaz.

**Paketle gelen ön yüzle izin listesi.** `whitelist` ayarlanırsa loopback listelenmedikçe ön yüz trafiği (loopback) reddedilir. Paketle gelen ön yüzle birlikte `127.0.0.1` ve `::1` adreslerini `whitelist` içine ekleyin. Bu durumda izin listesi ve engelleme listesi yalnızca arka uca doğrudan erişimi yönetir; çünkü ön yüz tarayıcı adreslerini gizler.

## Uygulama ve doğrulama

- [deeptutor/api/security_guard.py](../../deeptutor/api/security_guard.py)
- [tests/api/test_security_guard.py](../../tests/api/test_security_guard.py)
