# Ajanınızla DeepTutor'u kurma ve sorunlarını giderme

[Handbook](README.md) · [Development](DEVELOPMENT.md) · [Modules](MODULES.md) · [Storage](DATA_STORAGE.md)

Bu kılavuz, bir kullanıcı için DeepTutor'u kuran, yapılandıran ve doğrulayan
veya mevcut bir kurulumdaki sorunları araştıran harici bir ajana yöneliktir.
Mevcut bir sorun için kurulumu tekrarlamak yerine [Sorun giderme](#6-sorun-giderme)
bölümüyle başlayın. CLI'a genel bakış için [SKILL.md](../../SKILL.md) dosyasını okuyun.
Terminal ve dosya erişimine ihtiyacınız vardır; bu akış MCP veya ajana özgü bir
eklenti gerektirmez.

## 1. Hedefi belirleme

Yalnızca eksik bilgileri sorun ve yanıt beklerken bağımsız hazırlıklara devam
edin:

- Kurulum klasörü ve varsa mevcut DeepTutor checkout'u.
- Tam Web uygulaması mı yoksa yalnızca CLI mı; README'deki kurulum istemi için
  varsayılan olarak tam uygulamayı seçin.
- Hedef sürüm veya dal. Bu kılavuz, 1.7.0 modüler düzeni dahil olmak üzere güncel
  `dev` dalını anlatır; eski bir kararlı sürüm için eşleşen dokümantasyonu kullanın.
- LLM sağlayıcısı, tam model kimliği ve varsa özel/yerel uç nokta.
- Kimlik bilgisi kaynağı: mevcut bir ortam değişkeni, kullanıcının belirttiği özel
  bir yerel dosya veya sağlayıcı girişi. Anahtarları sohbette istemeyin.
- Bilgi tabanlarına/RAG'e şimdi ihtiyaç olup olmadığı; bunlar ayrıca embedding
  gerektirir. Arama isteğe bağlıdır.

Uygun checkout'ları/ortamları yeniden kullanın; yerel düzenlemeleri ve ayarları
koruyun. Kullanıcının mevcut `DEEPTUTOR_HOME` dizinini kullanın veya çalışma zamanı
dizinini (runtime home) açıkça seçin. Bu dizin `data/` klasörünün sahibidir; `data/`
dizininin kendisi veya öğrenme materyalleri için kullanılan Content Workspace
değildir.

## 2. Klonlama ve kurulum

Güncel `dev` dalının yeni bir tam uygulama kurulumu için (macOS/Linux örneği):

```bash
git clone --branch dev https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
cd web
npm ci --legacy-peer-deps
cd ..
```

Bu akış için Python **3.11–3.14** ve **Node.js 22 LTS** kullanın. Ortamı oluşturmadan
önce gerçek yorumlayıcıyı kontrol edin; `python3` daha eski olabilir. Windows'ta
desteklenen bir `py -3.X` ve `.venv\Scripts\Activate.ps1` kullanın. Kabuk durumu
araç çağrıları arasında korunmuyorsa, ortamın Python'unu ve `deeptutor` komutunu
mutlak yolla çağırın ve ortam değişkenlerini her sürece iletin.

Kaynaktan CLI kullanımı için yukarıdaki Python kurulumunu koruyun ve Node/npm
adımını atlayın. Bir kaynak ağacı, depoda bulunan tüm modülleri sunar; bu nedenle
yine de bunların Python bağımlılıklarına ihtiyaç duyar. 1.7.0 paket düzeninde
`deeptutor` asgari CLI'ı sağlar; `deeptutor-cli` aynı çekirdek için bir uyumluluk
takma adıdır. Gerektikçe özellik modülleri ekleyin; bu, yayımlanmış 1.6.15
paketlerinin düzeni değildir.

1.7.0 paket düzeni, eksiksiz Web uygulaması için `python -m pip install "deeptutor[full]"`
komutunu kullanır. Yalın `deeptutor` çekirdek sohbeti, CLI'ı ve SDK'yı içerir;
sunucuyu veya Web varlıklarını içermez. Geliştirme derlemeleri için yukarıdaki
kaynak akışını veya [Modules](MODULES.md) belgesinde açıklanan yerel wheel'leri
kullanın.

1.6.15'ten yükseltirken DeepTutor'u durdurun, mevcut çalışma zamanı dizinini
(runtime home) yedekleyin ve aynı `DEEPTUTOR_HOME` dizinini kullanmaya devam edin.
1.7.0'ı kurmak için `python -m pip install --upgrade "deeptutor[full]==1.7.0"`
komutunu çalıştırın, ardından yeniden başlatmadan önce `python -m pip check` ve
`deeptutor module list` komutlarını çalıştırın. Eski `deeptutor-cli` paketi
kuruluysa, yeni paketleri kurmadan **önce** kaldırın:
`python -m pip uninstall deeptutor-cli`. Eski wheel, paylaşılan Python dosyalarına
sahiptir ve tek komutla yapılan bir yükseltme, yeni kurulan çekirdeği silebilir.
Bu işlem çalışma zamanı dizinindeki verileri silmez. Ardından, yeni yalnızca
meta veri içeren uyumluluk takma adı için kurulum komutuna `deeptutor-cli==1.7.0`
ekleyebilirsiniz. Yalnızca CLI geçişi için, eski CLI'ı kaldırdıktan sonra
`deeptutor-cli==1.7.0` kurun ve ihtiyaç duyduğunuz özellik modüllerini ekleyin.

1.7.0'da yalın `deeptutor` paketini yükseltmek yalnızca çekirdeği seçer; tam
uygulama özellik kümesini korumak için `[full]` kullanın. Bu yükseltme sırasında
ayarları sıfırlamayın veya çalışma zamanı dizinini değiştirmeyin. Mevcut bir
checkout için güncellemeden önce dalını, commit'ini ve yerel düzenlemelerini
inceleyin; dalı sessizce değiştirmeyin veya ortamı bu örneğe uyacak şekilde
değiştirmeyin.


## 3. Soru sormadan başlatma

Başlatma, yapılandırma, tanılama ve başlangıç için aynı çalışma zamanı dizinini
(runtime home) kullanın. Bu örnek checkout kökünü kullanır; kullanıcının mevcut
bir dizini varsa onu kullanın:

```bash
export DEEPTUTOR_HOME="$PWD"
deeptutor init --non-interactive
deeptutor config providers
```

`init --non-interactive`, model seçmeden ve sağlayıcıyla iletişim kurmadan eksik
varsayılanları oluşturur ve kayıtlı ayarları korur. `--cli` da kabul edilir;
her iki modda da sihirbaz çalışmaz. Başlatma tek başına modelin hazır olduğunu
göstermez.

`config providers`, desteklenen LLM, embedding ve arama sağlayıcılarını varsayılan
uç noktaları ve LLM API biçimleriyle birlikte JSON olarak yazdırır. Buradaki
sağlayıcı kimliklerini kullanın. `init`, `config apply` ve `config show` ayrıca
`--home PATH` kabul eder; diğer komutlar için `DEEPTUTOR_HOME` değişkenini tutarlı
biçimde kullanın.

## 4. Yapılandırmayı uygulama

`setup.json` gibi UTF-8 kodlu bir JSON dosyası yazın ve model yer tutucusunu
kullanıcının seçimiyle değiştirin:

```json
{
  "llm": {
    "provider": "openai",
    "model": "YOUR_MODEL_ID",
    "api_key_env": "DEEPTUTOR_SETUP_LLM_KEY"
  },
  "system": {
    "backend_port": 8001,
    "frontend_port": 3782
  }
}
```

`api_key_env` ile adlandırılan değişken, CLI sürecinin ortamında bulunmalıdır.
Değeri yankılamadan kullanıcının yetkilendirdiği kaynaktan okuyun. JSON, gerçek
bir anahtarı değil, bir değişken adını içerir. Çözümlenen anahtarlar, sonraki
başlatmalar için DeepTutor'un özel ayarlarına kaydedilir. Proje kökündeki `.env`
dosyaları otomatik olarak yüklenmez.

```bash
deeptutor config apply setup.json --check
deeptutor config apply setup.json
deeptutor config show
```

`--check`; girdiyi, sağlayıcıları, adlandırılmış kimlik bilgilerini, uç noktaları
ve port çakışmalarını ayarları yazmadan ve sağlayıcılarla iletişim kurmadan
doğrular. Her iki mod da JSON üretir; geçersiz girdi 2 koduyla çıkar. Uygulama,
sağlanan her hizmet için özel bir **Agent Setup** profili seçer. Tekrarlamak aynı
profilleri günceller; diğer profiller ile atlanan hizmetler/ayarlar korunur. Her
seferinde kimlik bilgisi referansları dahil eksiksiz profiller sağlayın. Port
değişiklikleri yeniden başlatmada etkili olur.

| Bölüm | Zorunlu alanlar | İsteğe bağlı alanlar |
| :--- | :--- | :--- |
| `llm` | `provider`, `model` | `base_url`, `api_key_env`, `api_version`, `api_format` |
| `embedding` | `provider`, `model` | `base_url`, `api_key_env`, `api_version`, pozitif tamsayı `dimension` |
| `search` | `provider` | `base_url`, `api_key_env` |
| `system` | En az bir port | `backend_port`, `frontend_port` (1–65535 arasında, birbirinden farklı tamsayılar) |

Anahtarla kimlik doğrulayan uzak LLM/embedding sağlayıcıları `api_key_env`
gerektirir; yerel, OAuth ve `custom` uç noktalar bunu atlayabilir. Arama
gereksinimleri `config providers` çıktısından gelir. Varsayılan uç noktası
olmayan sağlayıcılar `base_url` gerektirir. LLM API biçimleri `auto`,
`openai_chat`, `openai_responses` ve `anthropic` değerleridir ve sağlayıcının
desteklenen listesine tabidir. Bilinmeyen alanlar, düz metin `api_key` alanları
ve URL'lerdeki kimlik bilgileri reddedilir. Gelişmiş ayarlar ve diğer hizmet
türleri Web Settings'te kullanılabilir olmaya devam eder.

Bilgi tabanları/RAG için ayrıca erişilebilir bir embedding modeli yapılandırın.
Örneğin:

```json
{
  "embedding": {
    "provider": "openai",
    "model": "text-embedding-3-small",
    "api_key_env": "DEEPTUTOR_SETUP_EMBEDDING_KEY",
    "dimension": 1536
  },
  "search": { "provider": "duckduckgo" }
}
```

Embedding `base_url` değeri, `https://api.openai.com/v1/embeddings` gibi tam
uç noktadır; katalog bunu Web arayüzünün yaptığı gibi normalleştirir. Mevcut bir
bilgi tabanının embedding modelini/boyutlarını değiştirmek, yeniden oluşturmanın
planlanmasını gerektirir. Gerekmiyorsa aramayı atlayın veya devre dışı bırakmak
için `none` seçin. DuckDuckGo anahtar gerektirmez; kullanılabilirlik kullanıcının
ağına bağlıdır.

Yerel Ollama için `{"llm":{"provider":"ollama","model":"YOUR_LOCAL_MODEL"}}`
kullanın ve Ollama'nın çalıştığını ve modelin kullanılabilir olduğunu doğrulayın.

OAuth için `config providers` çıktısındaki sağlayıcı kimliğini/modeli uygulayın,
ardından aynı çalışma zamanı dizininde (runtime home) sağlayıcının mevcut giriş
komutunu kullanın. Her türlü giriş etkileşimini kullanıcı tamamlar:

```bash
deeptutor provider login openai-codex
# Other supported flows: github-copilot, codebuddy
```

OpenAI Codex, DeepTutor'un kendi OAuth kimlik bilgilerini kullanır; harici
ajanın oturumu otomatik olarak yeniden kullanılmaz. Giriş bir model seçmez.

## 5. Doğrulama ve başlatma

```bash
python -m pip check
deeptutor module list
deeptutor doctor --format json
deeptutor doctor --online --format json
```

`pip check`, bağımlılık tutarlılığını denetler. Kullanıcının ihtiyaç duyduğu
modüller için `module list` çıktısını inceleyin: kurulu, etkin ve hazır ayrı
durumlardır. Web uygulaması server ve web modüllerine, RAG ise knowledge ve
parsing modüllerine ihtiyaç duyar; isteğe bağlı yetenekler kendi sahibi olan
modülleri gerektirir. Yalnızca çekirdek kurulum bu modülleri bilerek dışarıda
bırakır. Kaynak checkout'ları `module enable/disable` kullanır; wheel kurulumları
ayrıca `module install/uninstall` destekler. Değişikliklerden önce DeepTutor'u
durdurun ve yayımlanmamış modüller için `--wheelhouse /path/to/wheels` kullanın.
Bkz. [Modules](MODULES.md).

`doctor` yerel hazır olma durumunu denetler; `doctor --online` küçük bir gerçek
model isteği yapar ve sağlayıcı kullanım ücreti doğurabilir. Çıkış durumunu ve
zorunlu hataları inceleyin. Düzeltilebilir hataları giderin ve etkilenen
denetimleri yeniden çalıştırın. Kayıtlı ayarlar tek başına hazır olmanın kanıtı
değildir. LLM yoklaması isteğe bağlı embedding'i doğrulamaz; RAG istendiğinde
ayrıca Settings'te bağlantısını test edin ve kullanıcının onayladığı küçük bir
belgeyi alın/arayın.

Tam uygulama için:

```bash
deeptutor start --detach --no-browser
```

Başlatıcının bildirdiği gerçek URL'leri okuyun, backend `/health/ready` adresini
doğrulayın ve frontend'in yanıt verdiğini onaylayın. Varsayılanlar backend için
`http://127.0.0.1:8001` ve frontend için `http://127.0.0.1:3782` adresleridir;
farklıysa bildirilen portları kullanın. Hata durumunda başlatıcı günlüklerini
inceleyin. İlgisiz süreçleri durdurmak yerine `config apply` ile boş portlar
seçin. Yalnızca CLI için Web başlatmayı atlayın ve tur yürütmeyi doğrulayın:

```bash
deeptutor run chat "Reply with a short greeting." --format json
```

Bu da yapılandırılmış modeli kullanır. Yalnızca sıfır çıkış koduna veya ilk akış
olayına değil, başarılı bir yanıta ve turun tamamlanmasına bakın.

Şunlarla bitirin: checkout/ortam, çalışma zamanı dizini (runtime home), kimlik
bilgileri olmadan sağlayıcı/model, geçen denetimler, Web URL'si veya CLI çağrısı
ve kullanıcıdan beklenen kalan işlemler. Ayrılmış (detached) bir uygulama için
aynı dizinle `deeptutor stop` komutunu ekleyin. Kimlik bilgileri veya ağ erişimi
doğrulamayı engelliyorsa, kurulumu tamamlanmış ilan etmek yerine tamamlanmayan
adımı tam olarak belirtin.

## 6. Sorun giderme

Kullanıcının belirtisini araştırmak için aşağıdaki yaklaşımı kullanın. Denetimleri
kanıta göre seçin; her sorun için her komutu çalıştırmanız gerekmez.

1. **Çalışan örneği belirleyin ve belirtiyi yeniden üretin.** Kurulum yöntemini,
   kurulu sürümü veya kaynak commit'ini, etkin Python ortamını, çalışma zamanı
   dizinini (runtime home) ve gerçek hizmet URL'lerini tespit edin. Docker için
   konteyner yollarını/portlarını ana makine yollarından/portlarından ayırt edin.
   Başarısız olan eylemi, beklenen sonucu, yaklaşık zamanı ve ilgili son
   değişiklikleri sorun. CLI denetimlerinizin kullanıcıyla aynı örneği, hesabı ve
   çalışma alanını hedeflediğini doğrulayın; sağlıklı ikinci bir kurulum, hata
   hakkında size az şey söyler.

2. **En küçük yararlı kanıtı toplayın.** Yapılandırma/hazır olma durumu için
   `config show` ve `doctor`, gerçek bir LLM isteği için `doctor --online`, tur
   koordinasyonu, oturum depolaması ve geçiş ön kontrolü için `doctor runtime`
   kullanın. Doctor modlarından herhangi birine `--format json` ekleyin. Tek tek
   denetimleri inceleyin: en üstteki `ok: true`, RAG gibi isteğe bağlı hatalarla
   bir arada bulunabilir. Geçen bir LLM yoklaması; embedding'in, aramanın,
   araçların veya tarayıcının bağlantısının çalıştığını kanıtlamaz.

3. **Başarısız işlemi sınırları boyunca izleyin.** Görünür belirtiden başlayın ve
   işlemin ne kadar ilerlediğini belirleyin: tarayıcı → API → tur/yetenek →
   sağlayıcı, araç veya depolama. Kullanıcı arayüzü sorunları için tarayıcı
   konsolundaki ve ağdaki hataları inceleyin; sunucu günlüklerini zamana ve varsa
   `request_id`, `session_id` veya `turn_id` değerlerine göre ilişkilendirin.
   Ayrılmış (detached) başlatmalar için `<runtime-home>/data/user/runtime/launcher.log`
   dosyasını kontrol edin; uygulama günlükleri normalde, günlük ayarlarına bağlı
   olarak `data/user/logs/deeptutor.jsonl` içinde bulunur. Konteyner
   dağıtımlarında konteyner çıktısı da gerekebilir. İlgili dar bir bölümü okuyun
   ve paylaşmadan önce kimlik bilgilerini ve özel içeriği çıkarın.

4. **Aynı anda tek bir hipotezi sınayın.** Başarısız eylemi küçük bir yeniden
   üretime indirgeyin ve çalışan yolu başarısız olanla karşılaştırın. Örneğin,
   başarılı bir CLI turu ile başarısız bir Web turu, her ikisi de eşdeğer ayarları
   ve bağlamı kullanıyorsa dikkati tarayıcı/API yoluna yöneltir. Araştırmaya
   devam etmek için `--help`, `plugin info` ve checkout'taki kodu kullanın. Kök
   `AGENTS.md` mimariyi haritalandırır; yararlı başlangıç noktaları arasında
   `deeptutor_cli/`, `deeptutor/api/`, `deeptutor/runtime/`,
   `deeptutor/capabilities/`, `deeptutor/services/` ve `web/` bulunur. Sonuç
   çıkarmadan önce kaynağı kurulu sürümle eşleştirin.

5. **Odaklı bir düzeltme yapın ve özgün eylemi doğrulayın.** Mevcut verileri ve
   yapılandırmayı koruyun; keşif adımı olarak toptan yeniden kurulumlardan,
   sıfırlamalardan veya bilgi tabanı yeniden oluşturmalarından kaçının.
   Değişiklikten sonra yalnızca genel bir sağlık denetimini değil, kullanıcının
   başarısız olan işlemini yeniden çalıştırın. Gözlemleri hipotezlerden ayrı
   raporlayın. Sorun çözülmediyse kısa bir devir notu sunun: ortam/sürüm, yeniden
   üretim, beklenen ve gerçekleşen davranış, ilgili ve kimlik bilgilerinden
   arındırılmış hatalar, denenen denetimler ve bir sonraki yararlı araştırma.

## Uygulama ve doğrulama

- [deeptutor_cli/setup_config.py](../../deeptutor_cli/setup_config.py)
- [deeptutor_cli/doctor.py](../../deeptutor_cli/doctor.py)
- [tests/cli/test_agent_setup.py](../../tests/cli/test_agent_setup.py)
