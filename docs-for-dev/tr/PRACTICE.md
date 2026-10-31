# Alıştırma: soru bankası, yanlış sorular ve günlük tekrar

[El Kitabı](README.md) · [İlgili kılavuz](workspaces.md)

"Öğrenme Alanı → Question Bank" (`/space/questions`), tam soru bankasını ve yanlış soruları yönetmek için kullanılır; içe aktarma, arama, filtreleme, etiketleme ve favorilere ekleme desteklenir.
"Kişiselleştirilmiş Öğrenme → Practice" (`/learning/practice`), alıştırma istatistiklerini, günlük yanlış soru tekrarını ve aynı soru bankası, yanlış sorular ve içe aktarma işlevlerini sunar.
İki giriş noktası soruları ve tekrar kayıtlarını paylaşır; Öğrenme Alanı'ndaki Question Bank sayfası istatistik grafiklerini veya günlük tekrar panelini göstermez.
Question Bank ile yanlış sorular arasında geçiş yaparken geçerli giriş noktası ile ders, çalışma alanı gibi sorgu parametreleri korunur; eski `/space/questions` bağlantıları da çalışmaya devam eder.

## Günlük kullanım

- **Question Bank** tüm soruları içerir; arama, kaynak/materyal filtresi, favoriler, etiketler, çoklu seçimle yönetim ve sayfalamayı destekler.
- **Yanlış sorular** geçmişte yanlış cevaplanmış soruları ve yanlış sorulara elle aktarılmış soruları içerir. Etiketler bu iki koleksiyondan bağımsızdır; aynı soru birden çok etikete sahip olabilir.
- "Bu sayfayı çalış"a tıklayarak veya bir soru seçerek alıştırmaya başlayın. Önce cevaplayın, sonra referans cevabı ve açıklamayı görüntüleyin, en sonunda hatırlama durumunuzu geri bildirin.
- Tek seçmeli, çok seçmeli ve doğru/yanlış soruları, açık bir cevap bulunduğunda sunucu tarafından denetlenir; boşluk doldurma, kısa cevap ve güvenilir biçimde tanınamayan eski cevaplar öz değerlendirme kullanır ve bir model yapılandırmayı gerektirmez.
- Soru listesi varsayılan olarak cevapları gizli tutar; alıştırma ayrıntısı özgün cevabı korur ve en son alıştırma cevabını da gösterir.

Soru metni ve seçenekler her zaman görünür; "Cevap ve açıklama" bölümünü daraltmak yalnızca cevap işaretini, cevap kanıtını ve açıklamayı gizler.
Eski soru türü adları ve soru metninin hemen ardından gelen kod çitleri de uyumlu biçimde görüntülenir. Mastery Path sorularının kaynak bağlantısı ilgili öğrenme oturumuna geri döner.

Alıştırma sırasındaki yeni hatalar otomatik olarak yanlış sorulara eklenir. Tekrarda doğru cevap verildikten sonra da soru yanlış soru koleksiyonunda kalır; böylece geçmiş gözden geçirilebilir.
"Öğrenildi" olarak işaretlemek günlük planlamayı duraklatır, işareti kaldırmak onu geri getirir. Yeniden yanlış cevaplamak tekrarı yeniden açar.

## Kendi sorularınızı içe aktarma

`.xlsx`, `.csv`, `.tsv`, `.json` dosyaları desteklenir; tek seferde en fazla **500 soru, 5 MB, 64 sütun**.
Excel, etkin çalışma sayfasını kullanır; CSV/TSV, UTF-8 (BOM dahil) ve GB18030 kodlamalarını destekler.
Sayfa Excel ve CSV şablonları sunar. Eski `.xls` dosyalarını önce `.xlsx` olarak kaydedebilirsiniz.

| Sütun adı | Çince takma adlar | İçerik |
| --- | --- | --- |
| `question` | 题目、题干 | Zorunlu, soru metni |
| `question_type` | 题型 | `single_choice` tek seçmeli (单选), `multi_choice` çok seçmeli (多选), `true_false` doğru/yanlış (判断), `fill_blank` boşluk doldurma (填空), `short_answer` kısa cevap (简答); Çince soru türü adları da desteklenir |
| `A` … `J` | 选项A … 选项J | Seçmeli soru seçenekleri; en az iki geçerli seçenek gerekir |
| `correct_answer` | 答案、正确答案 | Zorunlu; tek seçmelide seçenek anahtarını, çok seçmelide `A,C` biçimini yazın; doğru/yanlışta `true` / `false` veya 对 (doğru) / 错 (yanlış) yazın |
| `explanation` | 解析 | İsteğe bağlı referans açıklaması |
| `tags` | 标签、分类 | İsteğe bağlı, virgül veya noktalı virgülle ayrılır |
| `difficulty` | 难度 | İsteğe bağlı zorluk metni |
| `user_answer` | 我的答案、作答 | İsteğe bağlı geçmiş cevap |

JSON dosyaları nesne dizisi kullanır; seçenekler `options` nesnesine veya dizisine konabilir, etiketler için dize dizisi kullanılabilir:

```json
[
  {
    "question": "哪些是质数？",
    "question_type": "multi_choice",
    "options": {"A": "2", "B": "3", "C": "4"},
    "correct_answer": "A,B",
    "explanation": "2 和 3 是质数。",
    "tags": ["数学", "数论"]
  }
]
```

"Question Bank" veya yanlış sorulara içe aktarmayı seçin; yüklemeden sonra önce önizlemeyi kontrol edin. Tek bir satır bile geçersizse içe aktarmayı onaylama açılmaz,
sayfa hatalı satır numaralarını gösterir. Excel formülleri önce değer olarak yapıştırılmalıdır. Onaydan önce hiçbir soru oluşturulmaz.

Question Bank'e aktarılan sorular başlangıçta "cevaplanmadı" durumundadır; yalnızca `user_answer` eklenmiş olması nedeniyle otomatik olarak yanlış soru sayılmaz.
Ders kapsamında içe aktarılan sorular o derse ait olur; içe aktarılan dosya adı materyal kaynağı olarak saklanır.
Aynı kapsamda soru metni, soru türü, seçenekler ve cevabı aynı olan yinelenen sorular etiketlerini birleştirir; mevcut soru ve cevap kayıtları korunur.
Gönderim başarısız olursa aynı önizleme yeniden denenebilir; başarılı bir gönderimin yeniden denenmesi aynı sonucu döndürür. Önizleme 24 saat geçerlidir.

## Alıştırma istatistikleri

"Kişiselleştirilmiş Öğrenme → Practice" sayfasının üst kısmı son 7 / 30 / 90 güne ait istatistikleri sunar; çizgi grafiği, sütun grafiği ve üç ölçüt arasında geçiş yapılabilir:

- **Yeni sorular**: soruların soru bankasına girdiği tarihe göre sayılır.
- **Yeni yanlış sorular**: her soru yalnızca ilk kez yanlış soru olduğu tarihte sayılır; sonraki yanlış cevaplar yeniden yeni yanlış soru olarak sayılmaz.
- **Tekrar sayısı**: başarıyla kaydedilmiş alıştırma gönderimlerine göre sayılır; aynı soru birden çok kez sayılabilir, ağ yeniden denemeleri yinelenen sayım oluşturmaz.

Sağdaki kaynak dağılımı, geçerli zaman aralığı ve ölçütle tutarlıdır. Günler tarayıcının yerel saat dilimine göre bölünür; kaydı olmayan günler 0 olarak gösterilir.
Fare veya dokunmayla belirli bir güne bakılabilir; grafiğe klavyeyle odaklanıldıktan sonra sol ve sağ ok tuşlarıyla günler arasında geçilir; "Günlük ayrıntıları göster" tam değer tablosunu sunar.
İstatistik dönemi, ölçüt ve grafik seçimi URL'de saklanır; sayfayı yenilemek veya bağlantıyı paylaşmak seçimi korur, ders ve çalışma alanı kapsamı da korunur.
Öğrenilmiş yanlış sorular ilk hata istatistiğini korur; silinmiş sorular ve silinmiş oturumlardaki sorular istatistiğe dahil edilmez.

## Günlük yanlış soru tekrarı nasıl planlanır

Yeni yanlış sorular varsayılan olarak ertesi günden itibaren tekrar edilir; eski yanlış sorular için plan, özgün oluşma zamanına göre sonradan oluşturulur. "Bugün", tarayıcının yerel saat dilimine göre belirlenir;
bugün vadesi gelen ve gecikmiş sorular o günün kuyruğunu oluşturur, önce vadesi en erken gelen sorular tekrar edilir ve her turda en fazla 20 soru bulunur.
Tekrardan sonra sonraki tura geçilebilir; ana sayfa bekleyen, gecikmiş ve bugün tekrar edilen soru sayısını gösterir.

| Geri bildirim | Sonraki planlama |
| --- | --- |
| Unuttum / Again | Yaklaşık 1 gün sonra; sonraki büyüme hızı düşürülür |
| Biraz zor / Hard | Mevcut aralık yaklaşık 1,2 ile çarpılır; sonraki büyüme hızı düşürülür |
| Hatırladım / Good | İlk başarılı hatırlamada veya unutmadan sonraki başarılı hatırlamada yaklaşık 3 gün; ardından hatırlama zorluğuna göre uzatılır |
| Çok kolay / Easy | Good'dan daha uzun; sonraki büyüme hızı ölçülü biçimde artırılır |

Nesnel bir soru yanlış cevaplandığında yalnızca Again seçilebilir. Aralık en fazla 365 gündür; gerçek vade anı, geri bildirim zamanından hesaplanır ve bulunduğu yerel tarihe atanır.
Öğrenilmiş sorular ve silinmiş kaynaklardaki sorular günlük kuyruğa girmez. İlerleme yalnızca başarılı kayıttan sonra ilerler;
yinelenen tıklamalar veya ağ yeniden denemeleri yinelenen sayım oluşturmaz, birden çok sekmeden gelen gönderim çakışmaları yeniden yüklemeniz için uyarı verir.

Bu sürüm, aralıklı tekrar fikrinden yararlanan, açıklanabilir ve test edilebilir bir **SM-2 tarzı soğuk başlangıç kuralı** kullanır.
Her kullanıcının unutma eğrisini eğitmez ve FSRS'in uygulandığını iddia etmez.
Referans projeler: [Anki](https://github.com/ankitects/anki), [FSRS4Anki](https://github.com/open-spaced-repetition/fsrs4anki).
Her tekrar kaydı saklanır; bu, zamanlama algoritmasının sonradan değerlendirilmesini veya taşınmasını destekleyebilir.

## Uyumluluk ve bakım

Mevcut Chat, Partner, kitap, Immersive Reading ve Mastery Path soru yazma arayüzleri kullanılmaya devam eder.
SQLite, mevcut soru yazımı sırasında yanlış soruları otomatik olarak toplar; her kaynağın yeni bir akışa ayrı ayrı bağlanmasını gerektirmez.
Özgün soru kimliği, etiket ilişkileri, özgün cevap, notlandırma sonucu ve oluşma zamanı korunur; tekrar kayıtları ayrı saklanır ve kaynak kanıtının üzerine yazılmaz.

Yeni tablolar `practice_review_state`, `practice_review_events`, `practice_imports` olup başlangıçta artımlı tablo oluşturma ve eski yanlış soruların sonradan oluşturulması yürütülür.
Her kullanıcı ve çalışma alanı kendi depolama bağlamını kullanmaya devam eder. Eski arayüzler uyumlu kalır; yeni arayüzler
`/api/question-notebook/practice` altında yer alır. Bir soru silindiğinde ilişkili tekrar kayıtları da temizlenir.
Uygulama sürümünü geri almadan önce yine de veritabanını yedekleyin; eski sürümler yeni tekrar planını gösteremez, ancak özgün soru bankası verileri yeni tablolara bağlı değildir.

Geliştirme kurulumu güncellendikten sonra yeni arayüzlerin kaydedilmesi için arka ucun yeniden başlatılması gerekir; ön yüz de karşılık gelen sürümü kullanmalıdır.

## Uygulama ve doğrulama

- [deeptutor/services/practice/](../../deeptutor/services/practice/)
- [deeptutor/api/routers/practice.py](../../deeptutor/api/routers/practice.py)
- [tests/api/test_practice.py](../../tests/api/test_practice.py)
