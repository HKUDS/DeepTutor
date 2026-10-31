# Çalışma alanları ve öğrenme verileri

[Handbook](README.md) · [İlgili kılavuz](DATA_STORAGE.md)

Normal sohbetlerde çalışma alanını giriş kutusundan seçin veya oluşturun; kitaplar, Mastery Path ve Immersive Reading (video öğrenme dahil) için çalışma alanı başlangıç penceresinde seçilir. Bir görevin materyalleri, oturumları, ilerlemesi, alıştırma kayıtları ve üretilen dosyaları seçilen çalışma alanında saklanır; hiçbiri seçilmezse "Default workspace" kullanılır. Kenar çubuğundaki geçmiş ve kişiselleştirilmiş öğrenme ana sayfası, geçerli hesabın tüm çalışma alanlarındaki kayıtları bir araya getirir; bir kaydı açtığınızda ait olduğu çalışma alanına geçilir.

Yükseltmeden sonra mevcut öğrenme verileri eski dizinlerinde kalır ve tamamı varsayılan çalışma alanına aittir. Eski sürümde sohbetlere atanan klasör bağlamaları geçmiş materyalleri otomatik olarak bölmez; yeniden düzenlemeniz gerekirse Settings → Personal → Data migration sayfasını kullanın.

## Depolama konumu

| İçerik | Depolama biçimi |
| --- | --- |
| Varsayılan çalışma alanının verileri | `data/user/workspace/`, `data/user/chat_history.db` gibi geçmiş yollar korunur; çok kullanıcılı kurulumlar kendi veri kök dizinlerini kullanır. |
| Kendi oluşturduğunuz çalışma alanlarının verileri | Çalışma alanı klasöründeki `.deeptutor/data/`; bağımsız oturum veritabanı, öğrenme materyalleri, ilerleme ve önbellek bunun içindedir. |
| Sohbette yüklenen ekler | Seçilen çalışma alanının `chat/attachments/<oturum kimliği>/` dizini; çalışma alanı dosya aramasıyla bulunabilir. Eski ekler, ilgili oturuma devam edildiğinde taşınır. `CHAT_ATTACHMENT_DIR` açıkça yapılandırılmışsa varsayılan çalışma alanı yine belirtilen dizini kullanır. |
| Kolayca incelenebilen üretilmiş dosyalar | Çalışma alanı klasöründeki `outputs/`; özelliğe, oturuma ve tura göre düzenlenir. |
| Ayarlar, kimlik bilgileri ve çalışma alanı kayıt bilgileri | Kullanıcı hesabına aittir; çalışma alanı değiştirmek bunları etkilemez. |
| Bellek | Hâlâ hesap genelinde paylaşılır; bu sürümde çalışma alanına göre yalıtılmaz. |
| Sistem çalışma alanı | Hassas bilgilerden arındırılmış yapılandırma anlık görüntüsü ile beceri ve MCP özeti; öğrenme oturumları için kullanılmaz. |

Model araçları, çalışma alanı dosya gezgini girişi üzerinden `.deeptutor` içindeki veritabanlarını okuyamaz. Yöneticinin açıkça paylaştığı kitaplar ve bilgi tabanları mevcut paylaşım izinlerine uymaya devam eder; kişisel öğrenme ilerlemesi çalışma alanı bazında ayrı ayrı saklanır. Yöneticiler paylaşılan bir dizini taşımadan önce ilgili yetkilendirmeleri ele almalıdır; önizleme bunu bildirir. Doğrudan bir kopya dışa aktarmak da mümkündür.

## Oluşturma, geçiş yapma ve arşivleme

Çalışma alanlarını Settings → Personal → Workspace sayfasında oluşturun, yeniden adlandırın veya arşivleyin. Kendi oluşturduğunuz bir çalışma alanı yoksa giriş kutusu ve öğrenme başlangıç penceresi yine de seçme ve yeni oluşturma girişi sunar. Otomatik oluşturulan dizini kullanabilir veya mevcut bir klasörü kaydedebilirsiniz; uzak dağıtımlarda girilen yol sunucu yoludur.

Geçiş yapmak geçerli sayfayı yeniden yükler ve eski çalışma alanının arayüz önbelleğini temizler. Başlatılmış yanıtlar ve materyal işleme görevleri, başlatıldıkları çalışma alanına yazmaya devam eder. Görev sayfaları ve dosya bağlantıları çalışma alanı bilgisini taşır; ana sayfa ve ayarlar önceki seçimi devralmaz. Bir kaydı çalışma alanları arasında açmadan önce gönderilmemiş metin ve ekler, o tarayıcıdaki özgün çalışma alanının taslağında saklanır; yeni sohbetin giriş kutusunda çalışma alanı belirtildiğinde taslak da buna aktarılır.

Mevcut normal sohbetler başka bir çalışma alanına taşınabilir; ilişkili alt sohbetler, ekler ve çıktılar birlikte taşınır. Öğrenme materyalleri veya başka oturumlar buna bağımlıysa, ilişkili içeriğin tamamını görmek için veri taşıma önizlemesini kullanın. Çalışmakta olan oturumlar taşınamaz. Arşivleme içeriği korur ve yeni yazmaları engeller; geri yüklendikten sonra öğrenmeye devam edilebilir.

## Çalışma alanı istemleri

Settings → Workspace sayfasında yeni bir çalışma alanı oluştururken istemi girin veya mevcut bir çalışma alanında "Workspace instructions" seçeneğine tıklayarak düzenleyin. Varsayılan çalışma alanı için de ayarlanabilir. Öğrenme hedeflerini, mevcut bilgi düzeyini, öğretim yöntemini ve yanıt tercihlerini yazabilirsiniz; en fazla 10.000 karakter olabilir. Temizleyip kaydederseniz varsayılan davranışa dönülür.

İstem, o çalışma alanındaki sohbetlere, problem çözmeye, etkin soru sormaya, yönlendirmeli öğrenmeye, Immersive Reading'e ve olağan görselleştirmelere otomatik olarak uygulanır. Geçerli içerik her turun başında sabitlenir; düzenlemeler bir sonraki turdan itibaren etkili olur. Deep Research, soru üretimi ve Manim animasyon akışları şu anda bu istemi kullanmaz.

## Partner'ın çalışma alanına bağlanması

Yeni bir Partner oluştururken "Library" adımında mevcut bir çalışma alanı seçilebilir; yapılandırma sayfasından bağlama sonradan da değiştirilebilir. Bağlandıktan sonra Partner, o çalışma alanının dosyalarını, bilgi tabanlarını, becerilerini ve not defterlerini sürekli olarak paylaşır; üretilen dosyalar o çalışma alanının `outputs/` dizinine yazılır; çalışma alanının kaynak atama kuralları ile Partner'ın araç anahtarları birlikte geçerlidir. Soul, sohbet kayıtları ve Partner belleği bağımsız kalır. Bağlamada yapılan değişiklik bir sonraki iletiden itibaren geçerli olur.

Varsayılan olarak yine "Partner private workspace" kullanılır; bilgi tabanları, beceriler ve not defterleri seçilip içine kopyalanabilir. Paylaşılan bir çalışma alanına geçmek önceki özel materyalleri silmez; bağlama kaldırıldıktan sonra bunlar kullanılmaya devam edebilir. Bilgi tabanı seçim listesi, alt ajan gibi Partner'ın getiremeyeceği bağlantıları içermez. Arşivlenmiş, kullanılamayan veya Partner sahibine ait olmayan çalışma alanları bağlanamaz; bağlı bir çalışma alanı kullanılamaz hale gelirse Partner hata verir, otomatik olarak başka bir çalışma alanına geçmez.

## Veri taşıma ve dışa aktarma

Settings → Personal → Data migration sayfasını açın, kaynağı, hedefi ve özellikleri seçin, ardından önizleyin. Önizleme dosya sayısını, boyutu, ilgili oturumları, otomatik eklenen bağımlılıkları ve taşınamama nedenlerini içerir. Kaynak veri taşınırken ona başvuran kitapların, öğrenme yollarının veya sohbetlerin de birlikte taşınması gerekebilir; önizlemede listelenen kapsamı esas alın.

Taşıma, özellik depolaması birimi üzerinden yapılır. Hedefte zaten özellik verisi bulunması veya veritabanı kimliği çakışması taşımayı engeller, üzerine yazılmaz; bu durumda hedef olarak boş bir çalışma alanı oluşturabilirsiniz. Yalnızca sayfanın açılmasıyla oluşan boş veritabanları mevcut öğrenme verisi sayılmaz. Çakışması olmayan normal oturumlar mevcut bir çalışma alanına taşınabilir.

Taşıma, kaynak verinin anlık görüntüsünü korur, veritabanlarını SQLite yedekleme arayüzüyle kopyalar ve dosya içeriklerini doğrular. Kaynak veri, hedefteki tüm içerik doğrulandıktan sonra temizlenir. Web sayfasını kapatmak başlamış bir taşımayı iptal etmez. Kesinti olursa son işlemlerde "Recover migration" seçeneğine tıklayabilirsiniz: işlenmeden önce özgün duruma geri dönülür, işlendikten sonra temizlik tamamlanır. Kurtarma bekleyen işlemler öğrenme verisi yazımını engeller; ayarlar sayfası yine kullanılabilir.

Geçmiş dizinler keşif listesinde gösterilir. Zaten desteklenen geçmiş öğrenme biçimleri, her özelliğin özgün yükseltme mantığını kullanmaya devam eder; ek eski dizinler dışa aktarılabilir veya hedef çalışma alanındaki `historical/` veri dizininde geçmiş arşivi olarak saklanabilir; özgün dosyalar korunur ve geçerli öğrenme kayıtlarına otomatik olarak karıştırılmaz. Dışa aktarılan ZIP paketi seçilen verileri, bağımlılıkları ve doğrulama manifestini içerir; hesap ayarlarını ve kimlik bilgilerini içermez. Bellek taşıma kapsamında değildir.

Kurtarma kopyaları, hesabın özel çalışma zamanı dizini altındaki `data-migrations/` içinde saklanır; arayüz tam yolu gösterir. Başarılı bir taşımadan sonra da kopya korunur. Veri hacmi büyükse kopyalama ve yedekleme için disk alanı ayırın ve harici programların bu dizinlere yazmasını duraklatın.

## Klasör konumunu değiştirme

Workspace → Move folder, çalışma alanı klasörünün konumunu değiştirir; çalışma alanı kimliği değişmez. Kök dizini değiştirmek yalnızca kök dizini izleyen çalışma alanlarını taşır; ayrı kaydedilmiş klasörler birlikte taşınmaz. Hedef klasör mevcut olmamalıdır; kopyalama doğrulandıktan sonra kayıt bilgileri güncellenir, özgün klasör yedek olarak kalır.

Varsayılan çalışma alanı, geçmiş verilerle uyumluluk için özgün depolama yolunu korur; klasör konumu ayarı, modele gösterilen dosyaları ve `outputs/` dizinini etkiler. Varsayılan çalışma alanının öğrenme verilerinin tamamını kendi oluşturduğunuz bir dizine almak istiyorsanız "Data migration" kullanın.

## CLI ve Python SDK

```bash
deeptutor run chat "解释傅里叶变换" --workspace ws_...
deeptutor chat --workspace ws_...
```

CLI'da `--workspace` belirtilmezse varsayılan çalışma alanı kullanılır.

```python
from deeptutor.app import DeepTutorApp

app = DeepTutorApp(workspace_id="ws_...")
sessions = await app.list_sessions()
```

SDK veya hizmet çağrılarını `deeptutor.services.workspace.context.workspace_context(workspace_id)` ile de sarmalayabilirsiniz. HTTP için `dt_workspace` sorgu parametresi veya `X-DeepTutor-Workspace` istek üstbilgisi kullanılır; WebSocket'te kapsam bağlantı kurulurken sabitlenir. Kendi oluşturduğunuz çalışma alanı kayıtlı olmalı ve geçerli hesaba ait olmalıdır.


## Becerileri, MCP'yi ve bilgi tabanlarını atama

"Learning Space" kaynakları tek yerden yönetir. Settings → Workspace sayfasında bir çalışma alanı oluştururken veya düzenlerken beceriler, MCP hizmetleri ve bilgi tabanları için ayrı ayrı "Inherit available resources" veya "Only selected resources" seçilebilir. İkincisi seçilip hiçbir öğe işaretlenmezse, çalışma alanı bu kaynak türünü devre dışı bırakmış olur. Atamayı kaldırmak kaynakları, kimlik bilgilerini, mevcut sohbetleri veya öğrenme kayıtlarını silmez; değişiklik sonraki turlardan itibaren geçerli olur.

Eski çalışma alanlarının taşınması gerekmez; atama yapılandırması kaydedilmemişse özgün kurallar geçerli olmaya devam eder: beceriler ve MCP hesap izinlerini izler, bilgi tabanları ise geçerli çalışma alanının özgün dizinini ve yönetici yetkilendirmelerini korur. Paylaşılan bilgi tabanları, kaynak kitaplığındaki öğeler seçilerek atanır; dizin kopyalanmaz veya taşınmaz, aynı ada sahip bilgi tabanları kaynağa göre ayırt edilir. Bilgi içeriği paylaşılırken her çalışma alanının öğrenme kayıtları yine ayrı ayrı saklanır.

Beceriler sayfasında "Account shared skills" ile belirli bir çalışma alanına özel beceriler arasında geçiş yapılabilir. Çalışma alanına özel beceriler o çalışma alanının `skills/` dizininde saklanır ve etkin, aynı adlı becerilerin arasında hesap genelinde paylaşılan, yöneticinin atadığı ve yerleşik sürümlerden önceliklidir. Özet, otomatik eklenen gövde ve isteğe bağlı okuma aynı çözümleme sonucunu kullanır. MCP bağlantı yapılandırması ve kimlik bilgileri hesap tarafından yönetilmeye devam eder; çalışma alanı yalnızca hizmet referansını saklar ve yöneticinin verdiği yetkileri genişletemez.

"Knowledge Center" hesabın ve arşivlenmemiş tüm çalışma alanlarının bilgi tabanlarını kaynaklarıyla birlikte gösterir; yeni kaynaklar varsayılan olarak hesap kaynak kitaplığına eklenir. Bir kaynağı silmeden önce ona başvuran çalışma alanları listelenir. Kaynak silindikten veya erişim izni kaybolduktan sonra başka kaynaklar otomatik olarak etkinleştirilmez; atama ayarlarında geçersiz öğeler için uyarı gösterilir. Çalışma alanı klasörünü taşımak kaynak başvurularını korur; bir bilgi tabanının verilerinin tamamı başka bir çalışma alanına taşınacaksa önce ilgili atamaları kaldırmalı veya dışa aktarma kopyasını seçmelisiniz.

Çalışma alanı ataması, DeepTutor'ın hangi MCP hizmetlerini sunacağını ve çağıracağını denetler. Harici hizmetin kendi dosyaları, veritabanları ve uzak hesap izinleri yine o hizmetin yapılandırmasıyla belirlenir; atama onun işlemini, kök dizinlerini veya uzak yetkilendirmesini otomatik olarak değiştirmez.

## Uygulama ve doğrulama

- [deeptutor/services/workspace/](../../deeptutor/services/workspace/)
- [deeptutor/services/partners/workspace_binding.py](../../deeptutor/services/partners/workspace_binding.py)
