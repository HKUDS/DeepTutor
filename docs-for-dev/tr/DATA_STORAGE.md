# Yerel veri kalıcılığı

[El kitabı](README.md) · [Çalışma alanları](workspaces.md) · [Konteynerler](CONTAINERIZATION.md)

DeepTutor'ın varsayılan kurulumu PostgreSQL, MySQL veya başka bir veritabanı
sunucusu gerektirmez. Kalıcı durum tek bir çalışma zamanı dizininin (runtime
home) altına yazılır; böylece bir dağıtımda bağlanacak, incelenecek ve
yedeklenecek tek bir ağaç bulunur. Bazı durumlar SQLite'ta saklanır; ayarlar,
üretilen çıktılar, bilgi tabanı dizinleri, önbellekler ve içe aktarılan kaynak
dosyaları ise sıradan dosyalar olarak kalır.

## Verilerin bulunduğu yer

Çalışma zamanı dizini (runtime home), DeepTutor'ı başlattığınız dizindir.
Başka bir dizin seçmek için `DEEPTUTOR_HOME` ayarlayın veya
`deeptutor start --home` / `deeptutor init --home` komutuna dizini verin.
Yayımlanan konteynerde aynı ağaç `/app/data` konumuna bağlanır.

Varsayılan yönetici kapsamı şu yerleşimi kullanır:

| Yol | İçerik |
| --- | --- |
| `data/user/settings/` | JSON/YAML ayarları ve sağlayıcı kimlik bilgileri |
| `data/user/chat_history.db` | SQLite oturumları, mesajları, turları, soru bankası girdileri ve alıştırma verileri |
| `data/user/.runtime/` | `workspaces.sqlite3` gibi özel çalışma zamanı durumu |
| `data/user/workspace/` | Varsayılan Content Workspace ve üretilen çıktılar |
| `data/user/workspace/notebook/` | Favori koleksiyonlar ve dizinleri (JSON dosyaları olarak; eski dizin adı) |
| `data/user/workspace/co-writer/documents/doc_<id>/manifest.json` | Yazılan not sayfaları, bloklar, revizyonlar ve sayfa üst verileri |
| `data/user/logs/` | Uygulama günlükleri |
| `data/knowledge_bases/` | Bilgi tabanı dizinleri ve sürümlü kaynak verileri |
| `data/parse_cache/` | Paylaşılan belge ayrıştırma önbelleği |
| `data/users/<user-id>/` | Yerel çok kullanıcılı kimlik doğrulama etkinken kullanıcıya özel çalışma alanı kökleri |
| `data/partners/<partner-id>/` | Sentetik Partner çalışma alanları |
| `data/system/` | Hesaplar, izinler, denetim kayıtları, dizinler ve sahip kimlik bilgileri |

Seçili bir Content Workspace `data/user` dışında olabilir. Bu durumda özel
öğrenme durumu `<workspace>/.deeptutor/data/` altında bulunur; hesap ayarları,
kimlik bilgileri, Memory ve çalışma alanı kayıtları ise çalışma zamanı
dizininde kalır. Seçili çalışma alanının yolunu yazdırmak için
`deeptutor workspace show` komutunu çalıştırın.

Favoriler ve yazılan notlar ayrı depolardır. Eski `notebook_entries` SQLite
tablosu soru bankası girdilerini tutar; yazılan not blokları veya favori
koleksiyonlar için depolama alanı değildir. Seçili bir harici çalışma alanında
bu dosya tabanlı depolar, aynı `notebook/` ve `co-writer/documents/` alt
dizinleri kullanılarak özel `.deeptutor/data/workspace/` ağacının altında
bulunur. Hem öğrenme kayıtlarını hem de not/favori içeriğini korumak için
gizli `.deeptutor` dosyaları dahil çalışma alanının tamamını yedekleyin.

## Veritabanı desteği

SQLite, desteklenen yerel arka uçtur. Desteklenen bir PostgreSQL veya MySQL
bağlantı ayarı yoktur; `DATABASE_URL` veya benzer bir ortam değişkenini
ayarlamak DeepTutor depolamasını yönlendirmez.

PocketBase, `data/user/settings/integrations.json` üzerinden yapılandırılan
isteğe bağlı bir entegrasyondur. Desteklenen oturum koleksiyonlarını
PocketBase'te saklar, ancak bir PostgreSQL bağdaştırıcısı değildir ve tüm
çalışma zamanı durumunu PocketBase'e taşımaz. Ayarlar, kimlik bilgileri, bilgi
tabanı dizinleri, ayrıştırma önbellekleri, günlükler ve çalışma alanı
çıktıları çalışma zamanı ağacında kalır. Mevcut PocketBase modu tek
kullanıcılıdır; desteklenen yerel çok kullanıcılı JSON/SQLite yerleşimi için
`integrations.pocketbase_url` değerini boş bırakın.

## Durumu inceleme ve yedekleme

DeepTutor veri oluşturduktan sonra, çalışma zamanı dizininizden özel çalışma
zamanı ağacındaki SQLite veritabanlarını listeleyin:

```bash
find data -type f \( -name '*.db' -o -name '*.sqlite3' \) -print
```

Seçili bir harici Content Workspace için özel veritabanı dosyalarını inceleyin:

```bash
workspace="$(deeptutor workspace show | sed -n 's/^Path: //p')"
if [ -d "$workspace/.deeptutor/data" ]; then
  find "$workspace/.deeptutor/data" -type f \
    \( -name '*.db' -o -name '*.sqlite3' \) -print
fi
```

`data` dizinini veya bir çalışma alanını kopyalamadan önce DeepTutor'ı ve tüm
Partner süreçlerini durdurun. SQLite'ın etkin write-ahead log dosyaları
olabilir; uygulama çalışırken yalnızca `.db` dosyalarını kopyalamak son
işlemlerin kaybolmasına yol açabilir. Çalışma zamanı dizinindeki `data`
dizininin tamamını ve ayrıca ayrı olarak yapılandırılmış her Content
Workspace'i yedekleyin. Her kopyayı hassas kabul edin; kopyalar kimlik
bilgileri, özel sohbet metinleri ve yüklenen öğrenme materyalleri içerebilir.

## Uygulama ve doğrulama

- [deeptutor/runtime/home.py](../../deeptutor/runtime/home.py)
- [deeptutor/services/path_service.py](../../deeptutor/services/path_service.py)
- [deeptutor/services/workspace/context.py](../../deeptutor/services/workspace/context.py)
