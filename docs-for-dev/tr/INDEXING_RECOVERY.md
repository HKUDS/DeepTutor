# Uzun belge dizinleme ve kurtarma

[El kitabı](README.md) · [İlgili kılavuz](EVENTS_AND_PROGRESS.md)

Her bilgi tabanı, en son dizinleme çalıştırmasını `.indexing-run.json` içine
kaydeder. Files/detail görünümü, **Indexing recovery details** bölümünü sunar;
burada tek tek kaynak sonuçları, mevcut aşama ve aşamaya özgü sayaçlar, geçen
çalışma süresi, çıktıdan/etkinlikten bu yana geçen süre ve ölçülebilir
ilerlemeden bu yana geçen süre yer alır. Bir aşamanın son partiye ulaşması,
dizinin tamamının hazır olduğunun kanıtı değildir. Bilinmeyen iş, kesintiden
sonra bilinmeyen olarak kalır; hiçbir zaman başarılı bir belge olarak
sayılmaz.

`GET /api/knowledge-bases/{id}/indexing-readiness`, model indirmeden veya
sağlayıcıya istek göndermeden hafif bir ayrıştırıcı, biçim ve embedding
yapılandırması denetimi yapar. Hazır olma durumu; sonraki indirmelerin,
kullanılabilir RAM'in veya GPU belleğinin ya da bir sağlayıcının çalışma
zamanı yanıtının garantisi değildir. Çalışma zamanı hataları, sınırlandırılmış
ve kimlik bilgileri maskelenmiş nedenlerini kalıcı çalıştırma kaydında korur.

Yeniden deneme, mevcut içerik adresli ayrıştırıcı önbelleğini kullanır:
kaynak baytları ve ayrıştırıcı imzası eşleşmeli, kullanılabilir metin veya
bloklar hâlâ mevcut olmalıdır. MinerU bulut PDF dilimleri yalnızca doğrulanmış
kontrol noktalarını yeniden kullanır. Embedding'leri değiştirmek ayrıştırmayı
yeniden kullanabilir, ancak yeni embedding imzası için ayrı bir dizin sürümü
oluşturur. Kullanılabilir bir kontrol noktası olmayan, yarıda kalmış aşamalar
yeniden başlar; günlüğün kendisi ikinci bir önbellek değildir ve kısmi
embedding'ler uydurmaz.

İptal göreve özgüdür ve güvenli bir sınırda etkili olur. Yönetilen yerel
MinerU süreçleri de iptali gözlemler; 600 saniye boyunca çıktı vermezlerse
veya toplamda 7200 saniyeyi aşarlarsa başarısız olurlar. Diğer eşzamanlı
motorlar rastgele bir anda kesilemez; iptal, onlar dönene kadar beklemede
kalır. Takılmış bir LlamaIndex yürütücüsünün, gerçekten çıkana kadar aynı
süreçteki üst üste binen yeniden denemelere girmesi engellenir ve sahipliği
kaybettikten sonra adayını yayımlayamaz.

LlamaIndex yeniden oluşturmaları ve artımlı eklemeleri yeni sürüm dizinlerini
kullanır. Bir aday, kalıcılaştırılmış dizini yeniden yüklenene, vektörleri
doğrulanana ve saklanan bir vektörü kullanan bir getirme yoklaması bir düğüm
döndürene kadar yayımlanmamış kalır. Yayımlama üst verisi atomik olarak
yazılır. Dizinleme sırasında kaynak değişirse yayımlama reddedilir. Başarısız
veya kısmi bir aday, önceki sorgulanabilir sürümün üzerine yazmaz.
Tamamlanan ve başarısız olan kaynaklar, kısmi başarı dahil ayrı ayrı
raporlanır. Kalıcı günlük, etkin kullanıcı/çalışma alanı bilgi tabanı ile
sınırlıdır; bağlı/salt okunur bilgi tabanları mutasyon route'ları üzerinden
iptal edilemez.

## Uygulama ve doğrulama

- [deeptutor/knowledge/indexing_run.py](../../deeptutor/knowledge/indexing_run.py)
- [deeptutor/services/parsing/cache.py](../../deeptutor/services/parsing/cache.py)
- [tests/knowledge/test_indexing_run.py](../../tests/knowledge/test_indexing_run.py)
