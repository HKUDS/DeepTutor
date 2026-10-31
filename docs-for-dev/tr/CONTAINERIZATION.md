# DeepTutor konteynerleştirme

[Handbook](README.md) · [Agent setup](AGENT_SETUP.md) · [Storage](DATA_STORAGE.md)

Bu doküman, DeepTutor'ın bir konteyner imajından dağıtımını ele alır: önerilen
`docker run` yolu, salt okunur kök dosya sistemine sahip sertleştirilmiş rootless
Podman yolu, çalışma zamanı yapılandırması, isteğe bağlı PocketBase sidecar'ı ve
varsayılan duruşun gerekçesini oluşturan güvenlik notları.

PyPI / kaynak kurulumları için ana [README.md](../../README.md) dosyasına bakın. Bu
dosya yalnızca yayımlanmış imajın çalıştırılmasıyla ilgilidir.

---

## Genel bakış

Yayımlanmış `ghcr.io/hkuds/deeptutor` imajı, `python:3.11-slim` tabanı üzerinde,
tek bir konteyner içinde `supervisord` altında hem FastAPI arka ucunu (`:8001`)
hem de Next.js ön yüzünü (`:3782`) çalıştırır. Özel çalışma zamanı ağacı
(konteyner içinde `/app/data`) ayarları, kimlik bilgilerini, veritabanlarını,
belleği, bilgi tabanlarını ve günlükleri barındırır. Varsayılan Content Workspace
de burada bulunur; ancak bunun yerine `/workspace` altına ayrıca bağlanabilir.
Her ikisinin de yeniden başlatmalardan sonra korunması için çalışma zamanı ağacını
ve varsa ayrı Content Workspace'i bind mount ile bağlayın.

İmaj üç dağıtım biçiminde çalışacak şekilde hazırlanmıştır:

1. **`docker run`** — kolay yol. Rootful, yazılabilir rootfs, `/app/data` üzerinde
   tek bir bind mount.
2. **`docker compose`** (`docker-compose.yml`) — aynı imaj artı PocketBase
   sidecar'ı ve sandbox-runner sidecar'ı. Yine rootful, yazılabilir rootfs.
3. **`podman compose -f compose.yaml`** — sertleştirilmiş yol. Rootless
   (`userns_mode: keep-id`), salt okunur rootfs, yazılabilir sistem dizinleri
   yerine tmpfs, `./data` üzerinde bind mount.

3. biçimi mümkün kılan mimari değişiklik, URL bilgisinin artık ön yüz paketinde
bulunmamasıdır. Somut olarak:

- Paket, `NEXT_PUBLIC_API_BASE` yer tutucusu olmadan ve derleme çıktısı üzerinde
  `sed -i` yapılmadan derlenir. `web/lib/api.ts`, `apiUrl` ve `wsUrl` değerlerini
  tek satırlık geçiş fonksiyonları olarak dışa aktarır; böylece tarayıcı göreli
  yolları ön yüz üzerinden (`:3782/api/...`) getirir.
- `web/proxy.ts`, `/api/*` ve `/ws/*` isteklerini yakalar ve istek anında
  `DEEPTUTOR_API_BASE_URL` adresine yeniden yazar. Bu ortam değişkeni, konteyner
  entrypoint'i tarafından her başlatmada ayarlanır ve
  `data/user/settings/system.json` dosyasından okunur.
- `start-frontend.sh`, `PORT`/`HOSTNAME` değerlerini ayarlar ve
  `node /app/web/server.js` komutunu `exec` ile çalıştırır. Pakette hiçbir
  değişiklik yapılmaz.
- `supervisord` root olarak (PID 1) çalışır ve her programı (arka uç, ön yüz),
  programa özel `user=` yönergesiyle root olmayan `deeptutor` kullanıcısına
  (UID 1000) düşürür; böylece uygulama süreçleri root olmayan kullanıcıyla kalır.
  Ana makinede `userns_mode: keep-id` ile bu UID, ana makine UID'nize eşlenir;
  normal bir `docker run` ile ise konteyner içinde sıradan, ayrıcalıksız bir
  kullanıcıdır.

Kurulum başına tam kılavuz aşağıdadır.

---

## Docker (varsayılan)

Mümkün olan en basit dağıtım. Tek konteyner, tek özel veri birimi ve tek port
eşlemesi.

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

<http://127.0.0.1:3782> adresini açın. Konteyner ilk açılışta
`/app/data/user/settings/*.json` dosyalarını oluşturur; model sağlayıcılarını Web
Settings sayfasından yapılandırın. Yapılandırma, API anahtarları, günlükler,
çalışma alanı dosyaları, bellek ve bilgi tabanları `deeptutor-data` adlı
birimde kalıcı olur.

### Unraid / NAS bind mount'ları (PUID / PGID)

Unraid ve birçok NAS şablonu, appdata'yı UID 1000 **olmayan** bir ana makine
kullanıcısına (çoğunlukla `nobody:users` = 99:100 veya adlandırılmış bir paylaşım
kullanıcısı) ait olarak tutar. Bu ana makineler, konteyner içindeki `chown`
işlemini yeniden başlatmada da geri alır. İmaj yine de arka uç/ön yüzü root
olmayan `deeptutor` kullanıcısına düşürür; entrypoint, bu kullanıcının UID/GID
değerlerini birimle eşleşecek şekilde yeniden eşler:

```bash
docker run --rm --name deeptutor \
  -e PUID=99 -e PGID=100 \
  -p 127.0.0.1:3782:3782 \
  -v /mnt/user/appdata/deeptutor:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

Çalışma zamanı kullanıcısı `/app/data` dizinine yine yazamıyorsa entrypoint,
başlayıp daha sonra `Knowledge base not initialized (llamaindex)` hatasını
bildirmek yerine sahip/mod bilgisi içeren bir mesajla **çıkar**. Rootless Podman
eşlemeyi atlar (`CAP_SETUID` yoktur) ve mevcut kullanıcıyı korur. Uygulamanın
asla root olarak çalışmaması için `PUID=0` / `PGID=0` reddedilir.

### Ana makine Content Workspace'i seçme

Uygulama veri bağlama noktası; özel ayarları, kimlik bilgilerini, veritabanlarını,
Memory'yi ve diğer çalışma zamanı durumunu içerir. Bunu, ajanların okuyabildiği
**Content Workspace**'ten ayrı tutun. Bir ana makine klasörünü açmak için onu
sabit `/workspace` yoluna bağlayın ve dağıtımı bu yola kilitleyin:

```bash
mkdir -p "$PWD/deeptutor-workspace/outputs"
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  -v "$PWD/deeptutor-workspace:/workspace" \
  -e DEEPTUTOR_WORKSPACE_ROOT=/workspace \
  -e DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS=/workspace \
  ghcr.io/hkuds/deeptutor:latest
```

Birlikte verilen Compose dosyaları için:

```bash
DEEPTUTOR_WORKSPACE_HOST=/absolute/host/folder \
  python scripts/docker_compose.py -f docker-compose.yml up -d
```

Yardımcı betik, Compose başlamadan önce ana makine klasörünü ve içindeki
`outputs/` dizinini oluşturur; böylece root'a ait bind mount'lar önlenir. Değişken
verilmezse `./data/user/workspace` kullanılır. Konteyner her zaman `/workspace`
yolunu görür; bu sayede saklanan ayarlar ve modele yönelik yollar ana makineler
arasında taşınabilir kalır. Bu, bir başlangıç/dağıtım tercihidir ve
**Settings → Workspace** içinde kilitli olarak gösterilir.

`docker-compose.yml` ile sandbox runner, içerik ağacını salt okunur olarak ve
`/workspace/outputs` için yazılabilir bir katmanla birlikte alır; `/app/data`,
kullanıcı ayarları veya kimlik bilgileri almaz. Dolayısıyla üretilen programlar
seçilen içeriği okur ve yalnızca tura özgü çıktıyı yazar. Tek konteynerli ve
rootless Podman biçimleri, o konteynerde mevcut en iyi yalıtım arka ucunu kullanır
ve etkin düzeyi Workspace ayarlarında bildirir.

Notlar:

- **Yalnızca `3782` yayımlanmalıdır.** Tarayıcı yalnızca ön yüz origin'i
  (`:3782`) ile konuşur; tüm `/api/*` ve `/ws/*` trafiği, `DEEPTUTOR_API_BASE_URL`
  değerini (varsayılan `http://localhost:8001`) istek anında okuyan Next.js
  middleware'i (`web/proxy.ts`) tarafından konteynerin **içindeki** FastAPI arka
  ucuna iletilir. Arayüzün çalışması için `:8001` portunu ana makineye açmanız
  **gerekmez**. `:8001` portunu yayımlamak (`-p 127.0.0.1:8001:8001`) isteğe
  bağlıdır — yalnızca API'ye doğrudan erişmek (curl, betikler) veya hata ayıklamak
  için kullanışlıdır.
- **Farklı ana makine portları:** her `-p host:container` eşlemesinin sol tarafını
  değiştirin (ör. `-p 127.0.0.1:8088:3782`). `data/user/settings/system.json`
  içinde konteyner tarafı portlarını (`backend_port`, `frontend_port`)
  değiştirirseniz konteyneri yeniden başlatın ve her eşlemenin sağ tarafını buna
  uyacak şekilde güncelleyin.
- **Ayrık çalıştırma:** `-d` ekleyin, ardından izlemek için `docker logs -f deeptutor`,
  durdurmak için `docker stop deeptutor` kullanın; adı yeniden kullanmadan önce
  `docker rm deeptutor` çalıştırın. `deeptutor-data` birimi, özel çalışma zamanı
  verilerini ve varsayılan Content Workspace'i yeniden başlatmalar boyunca korur;
  ayrıca bağlanmış bir Content Workspace ise ana makinedeki yolunda kalıcı olur.

### Geçici yerel Codex OAuth köprüsü

OpenAI Codex, tarayıcıyı sabit loopback portları olan `1455` veya `1457`
adreslerine yönlendirir. Varsayılan konteyner ağı, ana makinenin loopback'inden
ayrıdır; bu nedenle her iki portu yalnızca oturum açma sırasında Web ön yüzüne
yayımlayın. Geçici köprüyü başlatmadan önce her iki ana makine portu da boş
olmalıdır.

`docker run` için normal konteyneri durdurun ve aynı imajı ile veri birimini,
iki ek yalnızca loopback eşlemesiyle geçici olarak yeniden çalıştırın:

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -p 127.0.0.1:1455:3782 \
  -p 127.0.0.1:1457:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

Compose için aynı geçici katmanı, normalde kullandığınız temel dosyaya ekleyin:

```bash
# Source build with sidecars
python scripts/docker_compose.py \
  -f docker-compose.yml -f compose.codex-oauth.yaml \
  up -d --force-recreate deeptutor

# Pre-built GHCR image
python scripts/docker_compose.py \
  -f docker-compose.ghcr.yml -f compose.codex-oauth.yaml \
  up -d --force-recreate deeptutor

# Rootless Podman
podman compose -f compose.yaml -f compose.codex-oauth.yaml \
  up -d --force-recreate deeptutor
```

**Settings → Models → OpenAI Codex → Sign in with Codex** adımını tamamlayın.
Durum **Connected** olduktan sonra geçici `docker run` konteynerini durdurun ve
yukarıdaki normal komuta dönün. Compose için aynı temel komutu
`compose.codex-oauth.yaml` olmadan yeniden çalıştırın; geçici port bağlamalarının
kaldırılması için `--force-recreate deeptutor` seçeneğini koruyun.

Bu işlem `1455` ve `1457` ana makine portlarını serbest bırakır; kimlik bilgileri
kalıcı `/app/data/system` ağacında kalır. Her geri çağrı eşlemesini `127.0.0.1`
adresine bağlayın ve asla bir LAN'a veya genel arayüze açmayın — katman,
yalnızca `/auth/callback` yolunu değil, ön yüzün **tamamını** bu iki portta
yayımlar. Konteyner tarafı ön yüz portu `3782` olmayan manuel bir `docker run` için
sağ taraftaki `3782` hedeflerini değiştirin; `scripts/docker_compose.py`
yapılandırılmış özel portları kendisi işler. Tek konteynerli kurulumlarda, modelin
ürettiği kodun gizli bilgilerle aynı konteyner güven sınırını paylaşmaması
gerekiyorsa `sandbox_allow_subprocess` değerini `false` yapın.

### Tek seferlik geçiş: `docker-compose.ghcr.yml` artık `./data` dizininin tamamını bağlıyor

`docker-compose.ghcr.yml` eskiden yalnızca üç alt ağacı (`data/user`,
`data/memory`, `data/knowledge_bases`) bind mount ile bağlıyordu; bu nedenle geri
kalan her şey — `data/system` (JWT imzalama gizli anahtarı, hesaplar, izinler,
denetim günlüğü, kullanıcı başına Codex token'ları), `data/users` (kullanıcı
başına çalışma alanları), `data/partners`, `data/cli-apps` — konteynerin yazılabilir
katmanında yaşıyor ve her yeniden oluşturmada siliniyordu. Artık `docker-compose.yml`
ve `compose.yaml` ile uyumlu olarak tüm ağacı bağlıyor.

**Yükseltmeden sonraki ilk `up -d` komutundan önce** bu durumu çalışan
konteynerden dışarı kopyalayın; aksi halde boş ana makine dizinleri onu gölgeler ve
DeepTutor kimlik doğrulama gizli anahtarını yeniden üretir (herkesin oturumunu
kapatır) ve yönetici olmayan hesaplar olmadan başlar:

```bash
for tree in system users partners cli-apps; do
  docker cp "deeptutor:/app/data/$tree" "./data/$tree" 2>/dev/null || true
done
```

Adlandırılmış birim (`-v deeptutor-data:/app/data`) veya kaynaktan derleme Compose
dosyasını kullanan dağıtımlar hiçbir zaman etkilenmedi — onlar zaten tüm ağacı
kalıcılaştırıyordu.

### Uzak / ters proxy dağıtımları

Yaygın **tek konteyner** durumunda (bu imaj) bir API tabanı yapılandırmanız hiç
**gerekmez**. Tarayıcı, arayüzü sunan origin'e (`https://deeptutor.example.com`)
karşı göreli `/api/*` ve `/ws/*` istekleri gönderir; konteyner içindeki Next.js
middleware'i bunları `localhost:8001` üzerindeki arka uca iletir. Ters
proxy'nizi / TLS sonlandırıcınızı yayımlanan `:3782` portuna yönlendirmeniz
yeterlidir.

Bir API tabanını yalnızca arka ucun ayrı bir konteynerde çalıştığı **bölünmüş
dağıtım** için ayarlamanız gerekir. Ana makinedeki `data/user/settings/system.json`
dosyasını düzenleyin (`deeptutor-data` biriminin içinde — bağlama noktasını bulmak
için `docker volume inspect deeptutor-data`) ve ön yüz konteynerinin arka uç
konteynerine ulaşmak için kullandığı ağ içi adresi ayarlayın:

```json
{
  "next_public_api_base": "http://backend:8001"
}
```

Entrypoint bunu her başlatmada okur ve `proxy.ts` için
`DEEPTUTOR_API_BASE_URL` olarak dışa aktarır (öncelik: `next_public_api_base`,
ardından `next_public_api_base_external`, sonra `http://localhost:8001`).
Proxy **sunucu tarafında** olduğundan `DEEPTUTOR_API_BASE_URL` değerinin, ön yüz
*sunucusunun* arka uca ulaşmak için kullandığı adres olduğunu — tarayıcının hiç
görmediği bir URL olmadığını — unutmayın. `public_api_base` bir uyumluluk takma adı
olarak kabul edilir ve kayıt sırasında `next_public_api_base_external` alanına
normalize edilir.

CORS, API URL'lerini değil ön yüz **origin**'lerini kullanır. Kimlik doğrulama
kapalıyken DeepTutor, normal HTTP/HTTPS tarayıcı origin'lerine varsayılan olarak
izin verir. Kimlik doğrulama açıkken tam ön yüz origin'lerini ekleyin:

```json
{
  "cors_origins": ["https://deeptutor.example.com"]
}
```

### Ana makine LLM sağlayıcıları (Ollama / LM Studio / llama.cpp / vLLM / Lemonade)

Docker içinde `localhost`, ana makineniz değil konteynerin kendisidir. Ana
makinede çalışan bir model servisine ulaşmak için ana makine ağ geçidini kullanın
(önerilir):

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 -p 127.0.0.1:8001:8001 \
  --add-host=host.docker.internal:host-gateway \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

Ardından **Settings → Models** içinde sağlayıcı Base URL'sini
`host.docker.internal` adresine yönlendirin:

- Ollama LLM: `http://host.docker.internal:11434/v1`
- Ollama embedding: `http://host.docker.internal:11434/api/embed`
- LM Studio: `http://host.docker.internal:1234/v1`
- llama.cpp: `http://host.docker.internal:8080/v1`
- Lemonade: `http://host.docker.internal:13305/api/v1`

Docker Desktop (macOS/Windows) genellikle `host.docker.internal` adresini
`--add-host` olmadan çözer. Linux'ta taşınabilir yol bu bayrağı kullanmaktır.

**Linux alternatifi — ana makine ağı:** `--network=host` ekleyin ve `-p`
bayraklarını çıkarın. Konteyner ana makine ağını doğrudan paylaşır; bu nedenle
<http://127.0.0.1:3782> adresini (veya `system.json` içindeki `frontend_port`
değerini) açın; ana makine servislerine normal localhost URL'leriyle ulaşılabilir.

Ana makine ağı modunda süreçler doğrudan ana makine arayüzlerine bağlanır
(kapsamı daraltacak bir `-p 127.0.0.1:` öneki yoktur). Bunları LAN'dan uzak
tutmak için `BACKEND_HOST=127.0.0.1` ve `FRONTEND_HOST=127.0.0.1` ayarlayın — bunlar
uvicorn'un `--host` ve Next.js'in `HOSTNAME` değerlerini geçersiz kılar (ikisi de
varsayılan olarak `0.0.0.0`'dır). Bunları yalnızca `--network=host` ile kullanın:
bridge modunda loopback'e bağlanmak, yayımlanan `-p` port yönlendirmesini bozar.

---

## Podman / rootless / salt okunur rootfs

En güçlü varsayılan duruşu isteyen kullanıcılar için — rootless ve salt okunur
kök dosya sistemiyle — desteklenen başlangıç noktası `compose.yaml` dosyasıdır.
Aynı `ghcr.io/hkuds/deeptutor:latest` imajını çeker ve hepsinin çalışması için
entrypoint chown işlemine ve supervisord'un programa özel ayrıcalık düşürmesine,
URL ileten `proxy.ts` dosyasına ve ana makine tarafındaki bind mount'lara dayanır.

```bash
cp .env.example .env       # then edit if needed
podman compose -f compose.yaml up -d
podman compose -f compose.yaml ps
podman compose -f compose.yaml logs -f deeptutor
```

Rootless modun etkin olduğunu doğrulayın (`podman info | grep -i rootless`
çıktısı `true` olmalıdır).

`compose.yaml` neler yapar ve neden:

- **Her serviste `read_only: true`.** Konteynerin rootfs'i salt okunurdur. Tek
  yazılabilir yüzey, servis başına listelenen `tmpfs:` bağlamaları ile bind mount
  yapılmış `./data` ve Content Workspace dizinleridir.
- **`userns_mode: keep-id`.** Çalışma zamanının keep-id kullanıcı ad alanını
  kullanır. Gerçek eşlemeyi hedef ana makinede inceleyin; konteyner UID 0 veya UID
  1000 değerinin her ana makine hesabı için aynı şekilde eşlendiğini varsaymayın.
  `:U` bağlama seçeneği sahipliği konteyner eşlemesine göre ayarlar ve ana makine
  dizin sahipliğini değiştirebilir. Özel veri dizinleri kullanın ve yazma erişimini
  doğrulayın.
- **Çalışma zamanının yazmasını beklediği sistem dizinleri için `tmpfs:`
  bağlamaları.** `/tmp` (Python/Node geçici alanı), `/run` ve `/var/run`
  (pidfile'lar), `/var/log`, `/root`, `/home`. Boyutlar bilerek cömert tutulmuştur;
  ihtiyacınıza göre kısın.
- **Adlandırılmış birim yok.** Podman, adlandırılmış birimleri userns eşlemeli root
  (UID 100000) ile otomatik oluşturur; dolayısıyla 755 izinleri + yanlış sahip =
  ilk JSON yazımında `PermissionError`. Sahibi olduğunuz bir ana makine dizini
  üzerindeki bind mount'lar sorunsuz çalışır.
- **Yalnızca loopback port bağlamaları.** Her `ports:` girdisinde `127.0.0.1:`
  öneki. Tüm arayüzlerde yayımlamak için öneki kaldırın.
- **Sandbox-runner sidecar'ı yok.** `docker-compose.yml` biçimi, güvenilmeyen
  model üretimi kodu en az ayrıcalıklı bir konteynerde çalıştıran sertleştirilmiş
  bir sidecar içerir. Podman biçimi içermez — ana uygulama `bwrap`'e (Linux'ta,
  imajda kuruluysa) veya `system.json` içindeki `sandbox_allow_subprocess` ile
  denetlenen kısıtlı subprocess arka ucuna geri döner.

### `compose.yaml` dışında çalıştırma

`compose.yaml` bir başlangıç noktasıdır, tek biçim değildir. `podman run`
komutunu doğrudan kullanmak isterseniz aynı değişmezler geçerlidir:

```bash
mkdir -p data/user/settings
# Create defaults only when no settings exist; preserve existing configuration.
if [ ! -f data/user/settings/system.json ]; then
  printf '{}\n' > data/user/settings/system.json
fi

podman run --rm -d --name deeptutor \
  -p 127.0.0.1:8001:8001 \
  -p 127.0.0.1:3782:3782 \
  -v $(pwd)/data:/app/data:U \
  --read-only \
  --tmpfs /tmp:size=512m,mode=1777 \
  --tmpfs /run:size=32m,mode=0755 \
  --tmpfs /var/run:size=8m,mode=0755 \
  --tmpfs /var/log:size=64m,mode=0755 \
  --tmpfs /root:size=16m,mode=0700 \
  --tmpfs /home:size=16m,mode=0755 \
  --userns=keep-id \
  ghcr.io/hkuds/deeptutor:latest
```

Konteyner ayağa kalktıktan sonra arka uç ve ön yüz her zaman root olmayan
`deeptutor` kullanıcısı (UID 1000) olarak çalışır — `podman exec deeptutor ps -o user,pid,comm`
komutu `uvicorn`/`node` alt süreçlerini `deeptutor` olarak gösterir. `supervisord`
kendisi (PID 1), çalışma zamanının onu hangi UID ile başlattıysa o UID ile çalışır:
rootful Docker/Podman altında root, rootless podman + `userns_mode: keep-id` altında
ise ana makine kullanıcısı.

### Supervisord pidfile'ı

`[supervisord]` bölümünde **`user=` yönergesi yoktur**; bu nedenle supervisord
PID 1'in UID'siyle çalışır ve kendi ayrıcalığını düşürmeye çalışmaz; yalnızca alt
programları, programa özel `user=` yönergeleriyle `deeptutor` kullanıcısına
düşürülür. Buraya `user=root` yazmak (önceki bir tasarım) rootless keep-id modunu
bozuyordu: orada PID 1 root olmayan ana makine kullanıcısıdır ve `CAP_SETUID`
yetkisinden yoksundur; supervisord ayrıcalığı düşürmeyi reddeder ve başlangıçta
`Can't drop privilege as nonroot user` hatasıyla çıkar (bkz. supervisord'un
`options.py` dosyası).

Pidfile **`/tmp/supervisord.pid`** konumuna yazılır. `/tmp`, yukarıdaki her
çalıştırma yapılandırmasında `mode=1777` (herkes tarafından yazılabilir) olduğundan
pidfile, PID 1 root da olsa ana makine UID'si de olsa ve `/var/run` kimin olursa
olsun yazılabilir. Önceki bir derleme pidfile'ı root'a ait
`/var/run/supervisord.pid` konumuna yönlendiriyordu; rootless keep-id altında root
olmayan PID 1 bunu yazamıyor ve her başlangıçta kozmetik bir
`CRIT could not write pidfile` kaydı düşüyordu. Pidfile'ı `/tmp` içine koymak,
`/var/run` sahibine ve moduna olan bu bağımlılığı tamamen ortadan kaldırır.

---

## Çalışma zamanı yapılandırması

Ayarlayabileceğiniz hemen her şey, veri ağacının içindeki `data/user/settings/`
altında bulunur. Konteyner entrypoint'i, her başlatmada ilgili ortam
değişkenlerinden oluşan bir listeyi (`BACKEND_PORT`, `FRONTEND_PORT`,
`NEXT_PUBLIC_API_BASE`, `NEXT_PUBLIC_API_BASE_EXTERNAL`, `AUTH_ENABLED`,
`POCKETBASE_URL` vb.) temizler ve değerleri JSON dosyalarından yeniden dışa
aktarır. Yani: JSON dosyalarını düzenleyin, yeniden başlatın; bunları compose ortam
değişkenleriyle yönetmeye **çalışmayın**.

| Dosya | Amaç |
|:---|:---|
| `system.json` | Arka uç/ön yüz portları, genel API tabanı, CORS, SSL doğrulaması, ek dizini |
| `auth.json` | İsteğe bağlı kimlik doğrulama anahtarı, kullanıcı adı, parola özeti, token/çerez ayarları |
| `integrations.json` | İsteğe bağlı PocketBase ve sidecar entegrasyon ayarları |
| `model_catalog.json` | LLM, embedding ve arama sağlayıcı profilleri; API anahtarları; etkin modeller |
| `interface.json` | Arayüz dili / tema / kenar çubuğu tercihleri |
| `main.yaml` | Çalışma zamanı davranış varsayılanları ve yol enjeksiyonu |
| `agents.yaml` | Yetenek/araç sıcaklık ve token ayarları |

Yeni bir kurulum için en ilgili iki ayar:

- **`system.json` → `next_public_api_base`** (ağ içi) ve
  **`next_public_api_base_external`** (bulut/harici geçersiz kılma). Entrypoint
  bunları okur ve `web/proxy.ts` tarafından kullanılan
  `DEEPTUTOR_API_BASE_URL` değerini dışa aktarır. `public_api_base` bir uyumluluk
  takma adı olarak kabul edilir ve kayıt sırasında
  `next_public_api_base_external` alanına normalize edilir.
- **`system.json` → `backend_port` / `frontend_port`**. Supervisor'ın konteyner
  içinde bağladığı konteyner portları. Bunları değiştirirseniz her `-p host:container`
  eşlemesinin sağ tarafını (veya `compose.yaml` dosyasının okuduğu `HOST_PORT_*`
  ortam değişkenini) buna uyacak şekilde güncelleyin.

Proje kökündeki `.env` dosyaları, uygulama yapılandırması olarak bilerek yok
sayılır. JSON/YAML dosyaları için önerilen düzenleyici Web **Settings** sayfasıdır;
her bölümün derin bağlantıları sayfanın kenar çubuğunda bulunur.

---

## PocketBase

PocketBase, isteğe bağlı bir kimlik doğrulama + depolama sidecar'ıdır.
`data/user/settings/integrations.json` içinde `integrations.pocketbase_url`
değerini `http://pocketbase:8090` olarak ayarlayıp `pocketbase` servisini ana
`deeptutor` servisiyle birlikte ayağa kaldırarak etkinleştirin. O çalışırken ana
uygulama, kullanıcı hesaplarını ve oturumları SQLite tek kullanıcılı düzenine geri
dönmek yerine PocketBase'de saklar.

`compose.yaml` içindeki `pocketbase` servisi (ve `docker-compose.yml` içindeki
düzeltilmiş bağlama), `./data` altındaki üç alt dizini — `/pb_data`, `/pb_public`,
`/pb_hooks` — bind mount ile bağlar; bu, mutlak yollar kullanan yukarı akış
`ghcr.io/muchobien/pocketbase:latest` imajının entrypoint'iyle eşleşir. Önceki
`docker-compose.yml` örneği `/pb/pb_data` yolunu bağlıyordu ve ilk başlatmada
`mkdir /pb_data: read-only file system` hatasıyla çöküyordu; bu PR bunu düzeltir.

PocketBase tek kullanıcılı bir entegrasyon olarak kalır — harici bir kullanıcı
deposu bağlamadıysanız çok kullanıcılı dağıtımlar için
`integrations.pocketbase_url` değerini boş bırakın.

---

## Sorun giderme

**Konteyner başlangıcında `CRIT could not write pidfile /var/run/supervisord.pid`.**
Yalnızca pidfile'ın `/tmp/supervisord.pid` konumuna taşınmasından önce derlenen
imajlarda görülür (`mode=1777`, her zaman yazılabilir); güncel imajlar bunu
üretmez. Denetlenen alt süreçler her iki durumda da ayağa kalkar — satır her zaman
kozmetikti. Çözüm: güncel bir imaj çekin (veya eski bir imajda `/var/run` tmpfs
değerini `mode=1777` yapın).

**Sayfa yükleniyor ancak Settings "Backend unreachable" diyor.** Arayüz arka uca
bir ana makine portu üzerinden değil, konteyner içi proxy üzerinden ulaşır; bu
yüzden bu hemen her zaman başlayamamış bir arka uçtur (`[program:backend]`
satırları için `docker logs deeptutor` çıktısına bakın) veya bölünmüş bir
dağıtımda yanlış bir `DEEPTUTOR_API_BASE_URL` değeridir — arayüzün ihtiyaç
duymadığı eksik bir `:8001` ana makine eşlemesi **değildir**.

**Podman ana makinesinde `Cannot connect to the Docker daemon`.**
`systemctl --user start podman.socket` komutunu çalıştırın (rootless) veya
`docker-compose` CLI'sinin podman soketini kullanması için
`DOCKER_HOST=unix:///run/user/$UID/podman/podman.sock` ayarlayın.

**Adlandırılmış birimde ilk JSON yazımında `Permission denied`.** Bu, userns
eşlemeli root sorunudur; sahibi olduğunuz bir ana makine dizinine bind mount'a
geçin veya birim bağlamasında `:U` kullanın.

**Unraid'de `Data directory is not writable` / `Knowledge base not initialized
(llamaindex)`.** Uygulama root olmayan `deeptutor` kullanıcısı olarak çalışır.
`PUID`/`PGID` değerlerini bind mount'un ana makinedeki sahibine ayarlayın (bkz.
[Unraid / NAS bind mount'ları](#unraid--nas-bind-mountları-puid--pgid)). Bunu aşmak
için konteyneri root olarak çalıştırmayın.

**Yeni bir imajda `sed -i` hataları.** Olmaması gerekir — çalışma zamanı artık
paketi değiştirmez. URL, istek anında iletilir. Bir tane görüyorsanız büyük
olasılıkla eski bir imajdasınızdır; `ghcr.io/hkuds/deeptutor:latest` imajını
yeniden çekin.

**Settings sayfası API tabanı URL'sini kabul etmiyor.** Ana makinedeki
`data/user/settings/system.json` dosyasını açın ve
`next_public_api_base_external` değerini doğrudan ayarlayın. Sayfa arayüzü
`public_api_base` (eski takma ad) alanına bağlıdır ve eski alan kayıt sırasında
yeniden normalize edilir.

---

## Güvenlik notları

- İmaj, `supervisord` başlatılmadan önce ayrıcalıkları root olmayan bir
  `deeptutor` kullanıcısına düşürür (varsayılan olarak UID 1000, rootful Docker
  altında ise `PUID`/`PGID`). Root olarak çalışan her şey entrypoint'in kendisi,
  `/app/data` üzerinde denenen bir chown ve ortam değişkeni dışa aktarımıdır.
  Uygulama süreçlerinin kendisi asla root kalmaz.
- `read_only: true` ile birlikte beklenen yazılabilir sistem dizinleri için
  `tmpfs:`, konteynerin kök dosya sisteminin çalışma zamanında değiştirilemez
  olması anlamına gelir. Listelenen tmpfs yolları veya bind mount yapılmış `./data`
  ağacı dışında yazmaya çalışan bir süreç başarısız olur.
- Ana makinede `userns_mode: keep-id`, bir konteyner kaçışının root'un değil,
  ana makine kullanıcınızın izinleriyle sonuçlanması demektir.
- Sandbox-runner sidecar'ı (`docker-compose.yml` içinde, `compose.yaml` içinde
  **değil**), güvenilmeyen model üretimi kod için en güçlü duruştur: bir sandbox
  kaçışı ana uygulamaya değil, uygulama gizli bilgileri olmayan, sadeleştirilmiş ve
  ayrıcalıksız bir konteynere düşer. Podman biçimi bunu rootless podman biçimi
  karşılığında feda eder; ana uygulama `bwrap`'e veya
  `sandbox_allow_subprocess` ile denetlenen kısıtlı subprocess arka ucuna geri
  döner.
- Kimlik doğrulama (`data/user/settings/auth.json` → `auth_enabled = true`),
  `/api/*` ve `/ws/*` yollarını `dt_token` çerezi aracılığıyla korur.
  `web/proxy.ts`, çerezin zorunlu olup olmadığına karar vermek için
  `DEEPTUTOR_AUTH_ENABLED` değerini okur (entrypoint tarafından her başlatmada
  dışa aktarılır).
- CORS, API URL'lerini değil ön yüz **origin**'lerini kullanır. Kimlik doğrulama
  açıkken `system.json` içindeki `cors_origins` alanını, dağıtımın sunduğu tam ön
  yüz origin'lerine ayarlayın.
- İsteğe bağlı istek taraması (hız sınırı, IP izin/engel listeleri, saldırı deseni
  taraması), `system.json` içindeki `security_guard` ve `guard` extra'sı
  (`DEEPTUTOR_EXTRAS: "guard"`) aracılığıyla kullanılabilir. Varsayılan olarak
  kapalıdır; bkz. [SECURITY_GUARD.md](SECURITY_GUARD.md).

## Uygulama ve doğrulama

- [Dockerfile](../../Dockerfile)
- [docker-compose.yml](../../docker-compose.yml)
- [docker-compose.ghcr.yml](../../docker-compose.ghcr.yml)
- [compose.yaml](../../compose.yaml)
- [scripts/docker_compose.py](../../scripts/docker_compose.py)
- [tests/scripts/test_docker_compose.py](../../tests/scripts/test_docker_compose.py)
