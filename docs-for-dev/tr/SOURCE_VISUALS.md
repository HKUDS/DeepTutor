# Bilgi tabanlarında kaynak görseller

[Handbook](README.md) · [İlgili kılavuz](INDEXING_RECOVERY.md)

DeepTutor, bir PDF veya EPUB ayrıştırıcısı görsel dosyaları ürettiğinde çıkarılan
kaynak görselleri koruyabilir. Bilgi tabanı (KB), ayrıştırıcının çıkardığı ve
doğrulanmış PNG, JPEG, GIF veya WebP baytlarını; belirlenimci bir varlık kimliği,
belge karması, ayrıştırıcı kimliği, kaynak konumlayıcısı, başlık ve yakın metinle
birlikte saklar. Yapılandırılmış ayrıştırıcı blokları ayrıca, mevcut olduğunda
sayfa dizinini ve sınırlayıcı kutuyu da korur.
Görsel kayıt, KB'nin `visual_assets/` dizini altında, vektör dizininden ayrı olarak
tutulur. Erişim denetimli
`/api/knowledge-bases/{kb_name}/visual-assets/{asset_id}` API rotası bu baytları
birebir sunar ve ham bir kaynak dosya silindiğinde görsel varlıkları da kaldırılır.

LlamaIndex KB işlem hattı her kaynak görsel için bir metin kaydını dizinler; böylece
bir metin embedding modeli bu kaydı başlığı ve bağlamı üzerinden getirebilir. `rag`
bu kaydı sohbet döngüsünde getirdiğinde, görüntü destekli bir yanıt modeli bir
sonraki isteğinde doğrulanmış görsel piksellerini alır. Yalnızca metin destekleyen
bir model ise başlığı ve bağlamı, piksellerin görülmediğine dair açık bir uyarıyla
birlikte alır. Desteklenen tüm çıkarılmış görseller saklanır, her görsel 5 MiB ile
sınırlıdır ve tek bir model devamında en fazla iki getirilmiş görsel gönderilir.
Belge başına saklama sayısı, bu model isteği bütçesinden bağımsızdır. Belge başına
bir şekil sayısı üst sınırı ya da KB genelinde 16 MiB'lik bir manifest üst sınırı
yoktur. Okunamayan manifestler yazma işlemlerini açıkça başarısız kılar ve korunur.

Mevcut çıkarma kapsamı seçilen ayrıştırıcıya bağlıdır. MinerU, yapılandırılmış PDF
şekilleri üretebilir. PyMuPDF4LLM, görsel çıkarma etkinleştirildiğinde PDF ve EPUB
görsellerini üretebilir, ancak Markdown çıktısı sayfa kutularını sağlamaz.
Varsayılan yalnızca metin ayrıştırıcısı ve mevcut Docling adaptörü kaynak görsel
varlığı üretmez. Yalnızca vektör çizim komutlarından oluşan görseller veya
kullanılabilir bir OCR motoru yapılandırılmadığında OCR gerektiren sayfalar eksik
olabilir.
Diğer RAG sağlayıcıları bu görsel manifestini anlamsal keşif için henüz dizinlemez.
Tam görsel ve PDF sayfa incelemesi, embedding motorundan bağımsızdır.

## Tam şekiller, özgün sayfalar ve kapsam

Bir KB'nin Files görünümünde bir belge seçin ve **Source visual coverage**
bölümünü genişletin. Bu bölüm saklanan şekilleri, sayfalanmış özgün görsel
bağlantılarını ve bilinen atlanmış, başarısız olmuş veya doğrulanmamış çıkarma
konumlarını gösterir. Ayrıştırıcının hiç görsel döndürmemesi, bir belgede görsel
bilgi bulunmadığını asla kanıtlamaz. Rapor çıkarmayı betimler; dizin hazır olma
durumunu veya kitaptaki her görseli onaylamaz.

Mevcut `rag` aracı ayrıca `source_path`, `figure`, `asset_id`, `page`,
`region` ve `source_hash` parametrelerini kabul eder. Tam bir belge yolu almak için
`kb_files` kullanın. Şekil ve tablo referansları türünü ve numarasını korur;
İngilizce/Çince etiketler eşdeğerdir. Farklı kaynaklar tarafından paylaşılan bir
etiket belirsizdir ve seçim yapılmasını gerektirir. Kavram keşfi için mevcut anlamsal
getirmeyi kullanın ve gerekirse kaynak dilinde bir sorgu yazın. Benzer bir şekli
eşleşme saymak yerine ortaya çıkan belgeyi, bölümü, başlığı ve sayfayı birlikte tutun.

Vektör çizimleri, seyrek başlıklar veya yerleşime bağlı tablolar için bir PDF
sayfasını doğrudan inceleyin. Basılı referansın tam keşfi yalnızca seçilen, kilitsiz
tek bir PDF'yi en fazla 2000 sayfaya kadar tarar; birden çok geçiş sayfa
seçenekleri olarak kalır. Bilinen bir sayfa bu keşif sınırından bağımsız olarak
seçilebilir. Oluşturma işlemi özgün PDF'yi yerel olarak okur; OCR/model indirmesi
veya bulut çağrısı yapmaz. Tam sayfalar yerleşimi korur; normalleştirilmiş
`region=[x0,y0,x1,y1]` kırpmaları sınırlı piksel bütçesini daha fazla ayrıntıya
harcar. Bir PDF sayfasındaki ayrıştırıcı kaynaklı panel grupları, tam sayfa olarak
çözümlenir. Yapılandırılmış tablo başlıkları/hücreleri/birimleri ve notlar,
sağlandıklarında metin kanıtı olarak kalır; doğrulama için özgün sayfa erişilebilirdir.

Sayfa incelemesi 512 MiB'a kadar PDF'leri, en fazla 8 milyon oluşturulmuş pikseli ve
5 MiB görsel baytını destekler. Kilitli/hasarlı PDF'lerin, geçersiz bölgelerin ve
okunamayan etiketlerin açık sınırlılıkları vardır. Diğer biçimler, desteklenen
çıkarılmış görselleri ve özgün belgeye erişimi korur; PDF oluşturma işlemi bunlara
sessizce uygulanmaz. Oluşturma ölçeğini artırmak, bir taramada bulunmayan bilgiyi
geri kazandırmaz.

Her açıklama özgün pikselleri ve bir kaynak konumu içerir. Başlıklar ve sayfa metni,
gözlemlenen görsel olgulardan ayrı tutulur. Ayrıntılı takip soruları için aynı
değişmez `asset_id` değerini yeniden getirin; `source_hash` sayfa bağlantılarını
korur. Uyumlu yeniden dizinleme eski varlık kimliklerini kullanılabilir tutar.
Değişmiş veya eksik kaynaklar raporlanır ve eski bir referans asla yeni materyale
yönlendirilmez. İki kaynağı ayrı, sınırlı çağrılarda karşılaştırın. Kanıtlardan
biri incelenemiyorsa bir sayfa/bölge seçin, kaynağı netleştirin veya desteklenen bir
karşılaştırmanın yapılamayacağını belirtin. Tüm kitabın görsel olarak yüklenmesi
veya zorunlu harici zenginleştirme gerekmez.

Sentetik regresyon fixture'ları 100 kaynak şekil ile vektör, yapılandırılmış tablo
ve çok panelli sayfalar içerir. Beklenen erken/orta/geç referanslar, Çinceden
İngilizceye şekil etiketleri, başlıklar/birimler/notlar, özgün baytlar, belirsiz
eşleşmeler, kullanılamayan pikseller ve değişen kaynaklarda çekimser kalma, dil
modelinin akıcılığından bağımsız olarak denetlenir.


## Kaynağa dayalı alıştırma ve öğrenme kanıtı

Guided Learning'de açıklama, alıştırma veya gözden geçirmeyi açıkça isteyin. Yalnızca
açıklama içeren bir turun soru sorması gerekmez; `mastery_note_explained`, neyin
öğretildiğini ustalık tanımadan kaydeder. Bir hedefi ertelemek, onu tamamlanmamış
olarak korur. Görsel anlayış gerektiren hedefler için taslak hedefleri
`required_visual_tasks` bildirebilir: `identification`, `relationship`,
`table_graph` veya `comparison`. Genel metin puanları bu görsel gereksinimleri
karşılayamaz. Hedef görünümü, kalan bağımsız kanıtı gösterir.

Bağlı bir KB'deki tam bir özgün şekil veya sayfa üzerinde alıştırma isteyin.
Öğretmen piksellerini getirir, ardından `visual` bağlamıyla bir `mastery_quiz`
sorar. Soru kartı özgün kanıtı ve belge/sayfa bağlantılarını gösterir. Numaralı
etiket tanımlama, kaynak destekli ilişki soruları, tablo veya grafik yorumlama ve
sınırlı iki kaynaklı karşılaştırmalar desteklenir. Otomatik bölütleme, uydurma
etiket maskeleri veya üretilmiş yedek diyagram kullanılmaz. Yüklenemeyen bir kaynak
görsel, öğrencinin soruyu atlamasına veya yardım istemesine izin vermeye devam
ederken gönderimi devre dışı bırakır.

Referans anahtarı, kanonik kaynak terminolojisini ve destekleyici bir başlığı,
açıklamayı veya sayfa alıntısını kullanır. Diğer diller dahil, açıkça doğrulanmış
eşdeğer terimler aynı soruyu yanıtlayabilir. Seçmeli sorular, desteklenen yanlış
yanıtları birbirinden ayırır; bilinmeyen serbest metin ifadesi, bulanık anahtar
sözcük notlandırması yerine açıklama ister. Belirsiz/çelişkili anahtarlar,
erişilemeyen veya değişmiş kaynaklar ve eksik model girdisi pikselleri
notlandırılmamış kalır ve olumsuz ustalık veya tutma kanıtı oluşturmaz. Bir şekil
URL'si veya bildirilmiş bir görüntü yeteneği yeterli değildir: etkin döngü, gerçek
yalnızca metin geri dönüşü dahil, kabul edilen sağlayıcı isteğinde eşleşen görsel
baytlarını denetler.

Görünür/bilinmeyen yanıt ipuçları, yardımın korunduğu ve daha zayıf gözden geçirme
kanıtı üreten yönlendirmeli alıştırmadır. Bağımsız ustalığı göstermezler. Referans
yanıtı açığa çıkaran tam bir sayfa yönlendirmeli kalır; doğrulanmış bir özgün sayfa
bölgesi, yanıt ipucu görünümün dışında olduğunda bağımsız yorumlamayı destekleyebilir
ve referans doğrulaması için tam kaynak korunur. Yakın zamandaki yardım, tekrarlanan
yanıt anahtarı maruziyeti ve bir sorudan sonra verilen yardım da mevcut tutma oturumu
sınırı üzerinden ayırt edilebilir kalır.

Kaynak incelemesi istemek için **Review or challenge this assessment** seçeneğini
kullanın. Mevcut `mastery_repair_question`, hatalı bir değerlendirmeyi geçersiz kılar
ve ustalık/hata/gözden geçirme etkilerini yeniden hesaplar. Görsel bir anahtarı
düzeltmek de kaynak desteği gerektirir; tek başına bir itiraz asla ustalık tanımaz.
Öğrencinin elle yaptığı geçersiz kılmalar kendi ayrı kaynağını korur. Kaynak/şekil
kimliği, hedef, görev, ipuçları/yardım, yanıt ve deneme kimliği yeniden başlatmadan
sonra da korunur. Bir aktarım yeniden denemesi tek bir deneme kaydeder; yeni bir soru
yeni kanıt kaydeder. Taslağın değiştirilmesi, güvenilen hedef kimliğini korur;
başarıyı başlığa veya konuma göre aktarmaz. Değerlendirilmemiş, açıklanmış, yardımlı
ve bağımsız olarak gösterilmiş çalışma birbirinden ayrı kalır.

Regresyon iş akışları; eşdeğer dilde yanıtlar, yanlış seçenekler, notlandırılmayan
belirsizlik, onarım, erteleme, tekrarlanan gönderimler, taslak değişimi, kaynak
değişiklikleri ve yeniden başlatma dahil olmak üzere bağımsız olarak belirlenmiş
sentetik numaralı şekiller, ilişkiler ve tablo değerleri kullanır. Bu desteklenen küme,
her görselin veya keyfi düzyazı yanıtın sınırsız notlandırılmasını vaat etmek yerine,
belirsizlik için açık bir kurtarma yolu sağlar.

## Görsel istekleri için token tahminleri

Sağlayıcı kullanım bilgisini döndürdüğünde DeepTutor bu bildirilen sayaçları kullanır.
Kullanım bilgisi olmadığında konuşma istatistikleri tahmin olarak işaretlenir. Geri
dönüş yöntemi, serileştirilmiş metni token başına yaklaşık 3,5 karakter üzerinden
sayar ve yapılandırılmış her görsel bloğu için 1.024 token ekler. Görsel URL'lerini
ve Base64 yüklerini metin tahmininin dışında tutar; böylece kodlanmış dosya boyutu
sayacı milyonlarca token'a şişirmez.

Görsel payı; çözünürlükten, ayrıntı düzeyinden, modelden ve sağlayıcıdan bağımsız,
kaba bir yer tutucudur; bir faturalandırma hesabı değildir. Bir turdaki her model
çağrısı, yeniden oynatılan görseller dahil, kendi girdisini yine de sayar. Mevcut
saklanmış tahminler bu değişiklikle yeniden yazılmaz ve konuşma içeriği korunur.

## MinerU bulut PDF dilimlerini sürdürme

Büyük bulut PDF'leri, Document Parsing ayarlarındaki
`engines.mineru.max_pages_per_part` ile dilimlenir (varsayılan 180; 1–200
aralığına sıkıştırılır). Bu gelişmiş ayar, eski MinerU ayar formu kaydedilirken
korunur. Yerel ayrıştırma ve küçük/PDF olmayan girdiler mevcut davranışlarını korur.

Birleştirilmiş içerik listesindeki `page_idx` değerleri, iç içe bloklar dahil, özgün
PDF'ye atıfta bulunur. Örneğin ikinci 180 sayfalık dilimin 0 numaralı sayfa dizini 180
olur. Geçersiz yerel dizinler, kaynak sayfaları sessizce yanlış etiketlemek yerine
ayrıştırmayı başarısız kılar. Parça başına diğer tanılama artefaktları özgün yerel
numaralandırmasını ve `partNN_` dosya adı önekini korur.

Tamamlanan dilim arşivleri, etkin çalışma alanının ayrıştırma önbelleği altında,
atılabilir başarısız ayrıştırma dizinlerinin dışında, `.mineru-segments/` içine
kaydedilir. Aynı kaynağı ve ayrıştırıcı ayarlarını yeniden denemek tamamlanmış
dilimleri yeniden kullanır; değişen bir belge, uç nokta, model, dil, OCR/formül/tablo
ayarı veya dilim boyutu yeni bir kontrol noktası kümesi başlatır. API token'ları ve
imzalı URL'ler kontrol noktalarına asla yazılmaz. Her arşiv yeniden kullanılmadan önce
SHA-256 ile denetlenir; eksik veya bozuk bir kontrol noktası yeniden indirilir. Eşzamanlı
işler yine de bir bulut isteğini yineleyebilir, ancak kontrol noktası yazımları
atomiktir. Önbellek yazma hataları, başarılı bir ayrıştırmayı başarısız kılmaz.

Bu arşivler, normal ayrıştırma önbelleği gibi, ayrıştırılmış belge içeriğini,
görselleri ve MinerU tarafından döndürülen kaynak kopyalarını içerir. Çalışma alanı
önbelleği temizlenene kadar saklanırlar; hiçbir ayrıştırma çalışmıyorken
`.mineru-segments/` dizinini silmek yalnızca sürdürülebilir ilerlemeyi atar.
Bu değişiklik, eski birleştirilmiş sayfa dizinlerinin normal ayrıştırma önbelleğinden
yeniden kullanılmaması için bulut ayrıştırıcı imzasını sürümler. Mevcut bilgi tabanı
dizinlerinin düzeltilmiş sayfaları kullanabilmesi için açıkça yeniden oluşturulması
gerekir.

## Yerel MinerU belgelerini yeniden deneme

Yerel MinerU yeniden denemeleri, kesintiye uğrayan belgeyi baştan yeniden başlatır;
CLI, bir çıkarım çağrısı içinde güvenilir bir kontrol noktası sunmaz. Uyumlu tamamlanmış
belge ayrıştırmaları, yalnızca embedding yapılandırması değiştiğinde de dahil olmak
üzere, yeniden deneme veya yeniden başlatmadan sonra yeniden kullanılabilir kalır.
Boş veya okunamayan önbellek çıktısı, tamamlanmış kabul edilmek yerine yeniden
ayrıştırılır.

Yeni yerel çıktı, mevcut bir ayrıştırmanın yerini almadan önce kullanılabilir markdown
veya içerik blokları açısından denetlenir. Başarısız denemeler artefaktlarını tanılama
için korur. Çalışma alanı ayrıştırma önbelleği içinde bunlar, etkilenen imzanın
yanındaki gizli `.failed-` dizinlerine, sonraki yeniden denemenin çalışma dizininin
dışına taşınır. Hiçbir zaman tamamlanmış önbellek girdisi olarak değerlendirilmezler.
Çalışma alanı ayrıştırma önbelleğini temizlemek bu tanılama artefaktlarını da kaldırır.
Kesintiye uğrayan yerel bir alt süreç, çağıran başka bir deneme başlatmadan önce
durdurulur.

## MinerU ile küçük taranmış PDF sayfaları

Bazı taranmış PDF'ler, tam çözünürlüklü bir sayfayı alışılmadık derecede küçük bir
fiziksel sayfa kutusuna kodlar. MinerU'nun resmi bulut arka ucu, bu sayfaları isteğe
bağlı olarak geçici bir yükleme kopyasında büyütebilir. Özgün dosya, sayfa sırası,
sıkıştırılmış görsel baytları ve yumuşak maskeler korunur; dil, OCR, model, formül ve
tablo ayarları yapılandırıldığı gibi kalır. Bu bir geometri geçici çözümüdür; daha iyi
OCR'ı veya keyfi etkileşimli PDF anlamlarının korunmasını garanti etmez.

Seçenek varsayılan olarak kapalıdır. Bir yönetici, mevcut
`PUT /api/settings/document-parsing` uç noktası üzerinden bu kısmi yük ile
etkinleştirebilir:

```json
{"engines": {"mineru": {"normalize_tiny_scans": true}}}
```

Devre dışı bırakmak için `false` kullanın. Seçenek ayrıca `document_parsing.json`
içinde `engines.mineru.normalize_tiny_scans` konumunda bulunur. Etkinleştirmek, bulut
ayrıştırma önbelleği imzasını değiştirir; eski ayrıştırmalar bozulmadan kalır. Mevcut
dizinler otomatik olarak yeniden oluşturulmaz. İsteğe bağlı
`deeptutor[parse-pymupdf4llm]` wheel ekstrası, gereken PyMuPDF bağımlılığını sağlar.
Bir kaynak çalışma kopyası için `python scripts/install_extras.py parse-pymupdf4llm`
komutunu kullanın
([modül kurulumu](MODULES.md#kaynak-çalışma-kopyası) bölümüne bakın).

Yalnızca en uzun kenarı 144 puntonun altında olan, metin içermeyen ve sayfanın en az
%80'ini en az 1200 DPI görünür yoğunlukta kaplayan yüksek çözünürlüklü bir görsele
sahip sayfalar uygundur. En uzun kenar 768 puntoya ölçeklenir. Döndürülmüş,
kırpılmış, ek açıklamalı, vektör içeren veya varsayılan olmayan UserUnit değerine
sahip sayfalar değiştirilmeden bırakılır. Yerel MinerU, özel bulut uç noktaları,
normal PDF'ler ve PDF olmayan girdiler mevcut davranışlarını korur. Geçici kopyalar
başarıdan veya başarısızlıktan sonra kaldırılır ve sıkıştırılmış görsel akışları
değişirse yükleme reddedilir.

## İsteğe bağlı görsel açıklama toplu işleri

Mevcut LlamaIndex görsel açıklama geçişi, görüntü isteği başına birden çok görsel
gönderebilir. `image_description_batch_size` değerini
`PUT /api/knowledge-bases/rag-pipelines/llamaindex/config` üzerinden ayarlayın, örneğin:

```json
{"image_description_batch_size": 4}
```

Varsayılan değer `1`'dir ve tek tek istekleri korur; kabul edilen değerler 1–8
aralığına sıkıştırılır. Etkinleştirildiğinde eşzamanlılık sınırları toplu işleri
sayar ve mevcut zaman aşımı, olası bölme denemeleri dahil tüm toplu işi kapsar.
Döndürülen başlıklar, yanıt sırasına göre değil, açık kimliklerle eşleştirilir.
Hatalı biçimlendirilmiş JSON/kimlik eşlemeleri ve açık bağlam taşması, daha küçük
gruplara bölünür ve sonunda mevcut tek görselli istemi kullanır. N görselli bir grup
en fazla 2N−1 tamamlama çağrısı yapar; bu mod için sağlayıcı yeniden denemeleri devre
dışıdır. Kimlik doğrulama ve hız sınırları, işteki sıraya alınmış grupları durdurur;
diğer API/aktarım hataları bölmeye yol açmaz.

Bu yalnızca mevcut LlamaIndex açıklama geçişinde sonradan işlenen görselleri etkiler.
Yapılandırılmış kaynak görseller için açıklamaları etkinleştirmez ve okuma
materyalinin başlıklarını değiştirmez. Toplu işler farklı, yapılandırılmış bir istem
kullanır ve tamamlanmış, başarılı grupları bağımsız tek görselli başlıklardan ayrı
olarak önbelleğe alır. Özet; sıralı görsel içeriklerini ve meta verilerini, istemleri,
model kimliğini ve yeniden deneme ilkesini içerir. Başarısız, eksik veya iptal edilmiş
gruplar önbelleğe alınmaz; başarılı bölünmüş gruplar yeniden kullanılabilir. Boyutu
tekrar `1` yapmak normal tek görselli yolu geri getirir. Model, birden çok görsel
bloğunu desteklemelidir; desteklenmeyen API yanıtları, bir yedek istek patlaması
olmadan raporlanır.

## Uygulama ve doğrulama

- [deeptutor/services/rag/visual_assets.py](../../deeptutor/services/rag/visual_assets.py)
- [deeptutor/services/rag/source_pages.py](../../deeptutor/services/rag/source_pages.py)
- [deeptutor/services/parsing/engines/mineru/](../../deeptutor/services/parsing/engines/mineru/)
- [deeptutor/learning/visual_practice.py](../../deeptutor/learning/visual_practice.py)
- [tests/services/rag/test_source_visual_grounding.py](../../tests/services/rag/test_source_visual_grounding.py)
