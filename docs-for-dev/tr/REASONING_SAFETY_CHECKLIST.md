# Uzun ufuklu akıl yürütme ve güvenlik kontrol listesi

[El kitabı](README.md) · [İlgili kılavuz](AGENT_SETUP.md#6-sorun-giderme)

Bir öğretim yanıtı güvenilmez göründüğünde, varsayımlarını yarı yolda değiştirdiğinde, zayıf kanıta atıf yaptığında veya öğrencinin seçtiği materyali yansıtmadığında bu kontrol listesini kullanın. Liste bilinçli olarak tanılama amaçlıdır: kullanıcıların yararlı kanıt toplamasına yardımcı olur ve bakımcıların sorunun bir istem (prompt) sorunu mu, getirme sorunu mu, bağlam sorunu mu yoksa bir ürün hatası mı olduğunu ayırt etmesine olanak tanır.

## Hızlı tanılama soruları

1. Öğrenci başlangıçta ne istedi ve hangi kısıtlar veya tanımlar hâlâ geçerli?
2. Hangi yetenek çalıştı, hangi araçlar etkindi ve hangi araç çağrıları gerçekten yapıldı?
3. Yanıt hangi bilgi tabanına, eke, okuma seçimine, kitaba veya web sonucuna dayandı?
4. Yanıt somut kanıtı alıntıladı, ona atıf yaptı veya onu başka sözcüklerle ifade etti mi; yoksa yalnızca otoriter mi göründü?
5. Önceki bir tur göz ardı mı edildi, aşırı mı uygulandı veya başka bir öğrencinin bağlamıyla mı karıştırıldı?
6. Model neyin bilinmediğini, belirsiz olduğunu veya seçilen materyalin dışında kaldığını belirtti mi?

## Hata kipleri

| Hata kipi | Yaygın belirtiler | Olası nedenler | Kontroller |
| --- | --- | --- | --- |
| Uzun ufuklu kısıtların kaybolması | Sonraki adımlar daha önceki bir tanımı, hedefi, gösterimi, kısıtı veya düzeltmeyi unutur | Bağlamın kırpılması, dal karışması, çok fazla araç gözlemi, kısıtların yeterince yeniden belirtilmemesi | Nihai istemin ilgili geçmişini, oturum dalını ve tur meta verisini karşılaştırın; davranışın değişip değişmediğini görmek için eksik kısıtı yeni bir turda yeniden belirtin |
| Getirme kayması | Yanıt konuyla ilgilidir ancak alakasız kaynaklar kullanır veya komşu bir soruyu yanıtlar | Belirsiz sorgu, bayat dizin, karışık kaynaklar, geniş top-k, eksik yeniden sıralama veya kaynak filtresi | Araç girdilerini ve getirilen parça kimliklerini inceleyin; aynı soruyu her seferinde tek bir bilgi tabanı veya ek üzerinde çalıştırın; bayat bir dizini yeniden oluşturun veya yenileyin |
| Zayıf kanıtla aşırı özgüven | Kesin bir yanıt, not, tanı veya öneri atıf içermez ya da çelişkileri yok sayar | Getirme sonucunun olmaması, düşük güvenli eşleşme, modelin önceki bilgisine başvurması, belirsizlik talimatının eksikliği | Getirmenin boş veya düşük puanlı sonuç döndürüp döndürmediğini kontrol edin; tam destekleyici pasajı isteyin; yalnızca kanıta dayalı talimatlarla yeniden deneyin |
| Geri bildirimin materyale dayanmaması | Açıklama, sınav yanıtı veya düzeltme yüklenen ders materyaliyle çelişir | Yanlış kaynağın seçilmesi, bayat kitap sayfası, uyuşmayan atıf konumlayıcısı, çelişen kaynaklar | Atıf yapılan konumlayıcıyı, seçilen materyali ve güncel kaynak sürümünü karşılaştırın; sayfa veya bölüm çapalarını ve kaynağın değişip değişmediğini doğrulayın |

## Getirme hata örüntüleri

Gözlemlenen davranışı en iyi tanımlayan örüntüleri işaretleyin:

1. **Getirme yok:** araç kullanılabilirdi ancak çağrılmadı.
2. **Yanlış kapsam:** getirme başka bir bilgi tabanında, Partner çalışma alanında, ekte veya kullanıcı bağlamında arama yaptı.
3. **Bayat kaynak:** belge veya dizin, getirme çıktıları üretildikten sonra değişti.
4. **Parça sınırında bölünme:** bir tanım, tablo, ispat, kod bloğu veya başlık yazısı ortadan kesildi.
5. **Konuya yakın kayma:** parçalar aynı sözcük dağarcığını paylaşır ancak farklı bir soruyu yanıtlar.
6. **Anahtar sözcük uyuşmazlığı:** kaynak, öğrencinin sorusundan farklı terminoloji kullanıyor.
7. **Çeviri uyuşmazlığı:** çevrilmiş bir sorgu ile kaynak dili örtüşmüyor.
8. **Yinelenen parçalar:** aynı pasaj diğer ilgili kanıtları dışarıda bırakıyor.
9. **Aşırı geniş top-k:** zayıf eşleşmeler az sayıdaki güçlü eşleşmeyi sulandırıyor.
10. **Eksik yeniden sıralama:** anlamsal ilk aşama adayları kullanılmadan önce iyileştirilmiyor.
11. **Çelişen kaynaklar:** kaynaklar birbirini tutmuyor ve model sessizce birini seçiyor.
12. **Doğrulanmamış harici kaynak:** bir web sonucu, otorite, tarih veya çapraz doğrulama kontrolleri yapılmadan kullanılıyor.
13. **Atıf uyuşmazlığı:** ifade ile atıf yapılan pasaj birbirini desteklemiyor.
14. **Konumlayıcı uyuşmazlığı:** bir sayfa, bölüm, başlık veya çapa yanlış konuma işaret ediyor.
15. **Boş veya filtrelenmiş sonuç:** erişim, ayrıştırma, MIME, dil veya meta veri filtrelemesi gereken parçayı ortadan kaldırdı.
16. **Uydurma kanıt:** bir alıntı, sayı, başlık veya atıf, döndürülen hiçbir kaynakta yer almıyor.

## Toplanacak kanıtlar

Bir issue açmadan önce asgari düzeyde ve gizliliği koruyan bir rapor hazırlayın:

- DeepTutor sürümü, işletim sistemi, Python ve Node sürümleri ve kurulum modu.
- Kullanılan yetenek ve model; akıl yürütme çabasının veya modele özgü bir ayarın değiştirilip değiştirilmediği dahil.
- Seçilen bilgi tabanları, ekler, Reading materyali, Book veya Partner çalışma alanı; paylaşılması güvenli olmadıkça özel belgeleri yüklemeden.
- İlgili kullanıcı isteği ve asistan yanıtı; kişisel veriler çıkarılmış olarak.
- Activity panelinden veya JSON çalıştırma çıktısından araç adları, argümanlar, sonuç özetleri ve atıf kimlikleri.
- Uyuşmazlığı yeniden üretmek için gereken getirilen parçalar veya atıf konumlayıcıları.
- Yeniden denemenin, tek bir kaynak seçmenin, dizini yeniden oluşturmanın veya kısıtı yeniden belirtmenin sonucu değiştirip değiştirmediği.
- İstek çevresindeki sunucu günlükleri; API anahtarları, belirteçler, yerel yollar, kullanıcı adları ve kişisel içerik çıkarılmış olarak.

Kimlik bilgilerini, özel öğrenci çalışmalarını, kişisel tanımlayıcıları veya gizli belgeleri paylaşmaktan kaçının. Yapıyı koruyan, uydurulmuş veya kısaltılmış bir kaynak alıntısı, bir getirme sorununu yeniden üretmek için genellikle yeterlidir.

## Issue rapor şablonu

```markdown
Capability:
Model:
DeepTutor version:

What the learner asked:
What DeepTutor answered:
Why the answer looks wrong:

Selected sources:
Tool calls observed:
Retrieved snippet or citation IDs:

Reproducible steps:
Expected behavior:
Actual behavior:
What I already tried:
```

## Uygulama ve doğrulama

- [deeptutor/agents/loop/](../../deeptutor/agents/loop/)
- [deeptutor/services/rag/](../../deeptutor/services/rag/)
