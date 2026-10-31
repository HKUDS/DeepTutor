# Bilimsel araştırma iş akışları

[El kitabı](README.md) · [İlgili kılavuz](TOOLS_AND_CAPABILITIES.md)

DeepTutor; bilimsel makale istekleri, makale aramasının etkin olduğu Chat ve Deep
Research için `preprint`, `research_audit` ve `research_lit` araçlarını bağlar. Bunlar
bağlama göre etkinleşen araçlardır ve [Araçlar ve yetenekler](TOOLS_AND_CAPABILITIES.md#bağlama-kuralları)
bölümünde anlatılan, kullanıcının açıp kapatabildiği sekiz araçtan ayrıdır.

- `preprint(paper, action="read", pages=[...])`, birincil arXiv PDF'ini okur, istenen
  sürümleri ve eski arşiv kimliklerini korur, SHA-256 değerini kaydeder ve sayfa
  düzeyinde metin ile özgün kaynak bağlantılarını döndürür. İndirmeler 32 MiB ile,
  PDF'ler 500 sayfayla sınırlıdır; bir geçişte en fazla 20 sayfa / 36,000 karakter
  okunur. Kapsam ve çıkarılabilir metnin eksikliği açıkça belirtilir.
- `preprint(..., action="figures")`, çağıran taraf sayfa belirtmedikçe başlık adayı
  sayfaları seçer. Otomatik şekil kırpması yaptığını iddia etmek yerine özgün sayfaları
  aslına sadık biçimde işler. Görme destekli bir model için isteğe yerel model bağlamına
  en fazla iki görüntü girer; pikseller kalıcı araç meta verilerine asla girmez.
  Bağlantılar kaynak sürümü ve sayfayı belirtir. İşleme, modelin her görüntüyü gerçekten
  incelediğini kanıtlamaz.
- `research_audit(paper, repository, ref="HEAD", files=[...], checks=[...])`, bir GitHub
  revizyonunu bir commit'e çözümler ve en fazla sekiz statik dosyayı okur. Alıntı
  denetimleri, hem makale hem de kod alıntılarının getirilen bu kaynaklarda bulunmasını
  gerektirir. Sayısal farklar anlamsal inceleme için adaydır: parametre eşlemesi,
  birimler, varsayılanlar ve etkin yollar yine de önemlidir. Local/admin yerel okumaları
  mevcut `GITHUB_TOKEN` ortam kimlik bilgisini kullanabilir; diğer hesaplar, bir dağıtım
  token'ını ödünç almak yerine kendi yetkili MCP bağlantılarını kullanır. Herkese açık
  API hız sınırı/erişim hataları doğrulanmamış başarısızlık olarak kalır. İş akışı,
  indirilen depo kodunu çalıştırmaz ve deneysel yeniden üretimi onaylamaz. Denklemler ve
  yöntemler için tam birincil metni kullanın; doğrulanmamış çalışma zamanı/ortam/veri
  denetimlerini raporlayın.
- `research_lit(topic, followups=[...])`, en fazla üç açık takip sorgusuyla birincil arXiv
  meta verilerini arar ve makale kimliklerini tekilleştirir. Matrisi kaynağı, yazarı,
  kanıt düzeyini ve kapsamı kaydeder. Uyum/uyuşmazlık atamadan önce makalelerin tamamını
  okuyun; Deep Research'ün APPEND kuyruğu, çelişkilerin ve kanıt boşluklarının özyinelemeli
  incelenmesini destekler.

Rapor; iddia, yöntem, veri, metrik, sonuç ve sınırlılığı makale sayfası ve commit-dosya
atıflarıyla karşılaştırır. Yazar bulguları, modelin çıkarımı, üretilmiş özetler ve topluluk
açıklamaları ayrı kanıt katmanları olarak kalır. Kullanılamayan getirme bir başarısızlıktır;
boş bir küme veya doğrulanmış bir bulgu değildir.

## alphaXiv ve kendi barındırdığınız araştırma MCP'si

Katalog, OAuth'lu ve dört araştırma okuma aracı (keşif, tam makale metni, sayfa
sorguları ve depo dosyaları) içeren resmî [alphaXiv MCP uç noktasını](https://www.alphaxiv.org/docs/mcp)
içerir. Kütüphane yazma araçları bu ön ayar tarafından etkinleştirilmez. Birincil kanıt
gerektiğinde `get_paper_content` ile `fullText=true` isteyin; varsayılan ara raporu
üretilmiş analizdir.

Chat ve Deep Research, bu araçlar için aynı hesap/çalışma alanı/partner izin görünümünü
kullanır. `preprint(action="mcp", mcp_tool="<qualified name>", arguments={...})`, ilan
edilmiş, yetkili bir araştırma okuma işlemini çağırabilir. Kendi barındırdığınız,
Feynman tarzı bir MCP sunucusu, bu bağlama üzerinden audit/lit/arxiv/alphaxiv işlemlerini
veya salt okunur tartışma/açıklama işlemlerini sunabilir.

`preprint(action="discussion")`, herkese açık alphaXiv makale sayfasını okur ve açıklama
kapsamını doğrulanmamış olarak işaretler: üretilmiş genel bakışlar ve dinamik olarak
dışarıda bırakılan yorumlar, birincil makale veya eksiksiz bir tartışma dışa aktarımı
olarak sunulmamalıdır. Güncel resmî MCP belgeleri, ayrı bir yorum uç noktası ilan etmez.
Yapılandırılmış bir sunucu `get_comments`, `get_discussions`, `get_annotations` veya
`get_errata` sunuyorsa, bu çıktı açıkça topluluk açıklama katmanı olarak işaretlenir;
kullanılamayan araçlar kullanılamaz kalır.

## Güvenilir özel MCP origin'leri

Bir yönetici, yönetici MCP kayıt defterinde `allow_private_network=true` ayarını
yaparak özel bir uzak sunucu origin'ini onaylayabilir. Düzenleyici bu ayarı gösterir;
devre dışı bir yönetici girdisi, paylaşımlı bir araç bağlantısı ilan etmeden onay işlevi
görebilir. Bir hesabın kendi sunucusu, aynı bayrağı yalnızca tam şeması, ana makinesi ve
portu geçerli bir yönetici onayıyla eşleştiğinde seçebilir.

```json
{
  "servers": {
    "research_origin_approval": {
      "url": "http://research.internal:8080/mcp",
      "allow_private_network": true,
      "enabled": false
    }
  }
}
```

İstisna yalnızca o origin için RFC1918 Docker/LAN adreslerine izin verir. Self-servis
loopback, bulut meta veri/link-local adresleri ve diğer özel origin'ler engelli kalır.
DNS ve onay, bağlantı/istek sınırlarında ve araç kabulünde denetlenir; yönetici bayrağını
iptal etmek, havuzlanmış bir bağlantının bir sonraki çağrısını engeller. Self-servis
yönlendirmeler devre dışı kalır; paylaşımlı aktarım yönlendirmeleri hedeflerine
bağlanmadan önce denetlenir. Bu ayar `web_fetch` işlevini veya yerel makale/depo
indirmelerini değiştirmez. Eski yönetici sahipli yerel/stdio yapılandırmaları özgün
davranışlarını korur. Yerel arXiv meta verileri işlem içinde hız sınırlamasına tabi
tutulur; sağlayıcı hız sınırı hataları görünür kalır. [arXiv API belgelerine](https://info.arxiv.org/help/api/user-manual.html) bakın.

## Uygulama ve doğrulama

- [deeptutor/tools/research_tools.py](../../deeptutor/tools/research_tools.py)
- [deeptutor/services/research/primitives.py](../../deeptutor/services/research/primitives.py)
- [tests/services/research/test_primitives.py](../../tests/services/research/test_primitives.py)
- [tests/services/research/test_mcp_boundaries.py](../../tests/services/research/test_mcp_boundaries.py)
