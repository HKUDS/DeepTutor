# Bilgi taşıma kılavuzu

[El kitabı](README.md) · [İlgili kılavuz](INDEXING_RECOVERY.md)

Bu kılavuz, Obsidian, Hermes veya Markdown tabanlı başka bir araçtaki mevcut notların güncel Knowledge Center'a taşınmasını kapsar. Mevcut DeepTutor verilerini çalışma alanları arasında taşımak için [çalışma alanı veri taşıma](workspaces.md) belgesini kullanın.

## Bir taşıma yolu seçin

| Yol | DeepTutor neyi tutar | En uygun durum | Ödünleşim |
| --- | --- | --- | --- |
| Bir Obsidian vault'unu bağlama | Vault'a canlı bir işaretçi | Obsidian'ı gerçek kaynak olarak kullanmaya devam etmek | Vault bir vektör dizinine kopyalanmaz, dolayısıyla bir RAG külliyatı değildir |
| Dizinlenmiş bir bilgi tabanı içe aktarma | `raw/` içine kopyalanan, ardından dizinlenen Markdown ve diğer desteklenen dosyalar | Kopyalanmış bir külliyatı seçilen getirme motoruyla aramak | Özgün notlardaki sonraki değişiklikler otomatik olarak içe aktarılmaz |

DeepTutor'ın özel, tek tıklamalı bir Hermes içe aktarıcısı yoktur. Hermes notlarını Markdown olarak dışa aktarın ve içe aktarılan bilgi tabanı yolunu izleyin. Dışa aktarımı önce not aracınızda kontrol edin; DeepTutor özel biçimleri dönüştürmez.

## Kaynağı hazırlayın

1. Kaynak vault'u veya dışa aktarımı bağlamadan ya da içe aktarmadan önce eksiksiz yedekleyin.
2. Notları `.md` veya `.markdown` olarak dışa aktarın. Not aracınız bu seçeneği sunuyorsa bağlantılı görsel ve belge varlıklarını da dahil edin.
3. Uygulama HTML veya başka bir biçimde dışa aktarıyorsa, bunu DeepTutor dışında Markdown'a dönüştürün, bir örneği inceleyin ve bağlantıların ile eklerin hâlâ çözümlendiğini doğrulayın.
4. Yukarıdaki tablodaki iki yoldan birini seçin. İkisini birden kullanabilirsiniz: not çalışması için canlı Obsidian vault'unu bağlayın ve getirilebilir bir dizin istediğinizde bir kopyasını içe aktarın.

## Obsidian'ı bağlayın

Obsidian birincil düzenleyiciniz olarak kalacaksa ve DeepTutor'ın aynı notlara göz atmasını ve ekleme yapmasını istiyorsanız bu yolu kullanın.

1. DeepTutor'da **Knowledge Center**'ı açın, **Create KB**'yi seçin, ardından **Link existing** ve **Obsidian**'ı seçin.
2. DeepTutor sunucusunun erişebildiği vault klasörünün mutlak yolunu girin, örneğin `/Users/example/Documents/MyVault`. Başka bir makineden bir yol girmeyin.
3. Bilgi tabanına ayırt edici bir ad verin ve bağlayın.
4. Chat'te o KB'yi seçin. Obsidian araçları bu durumda seçilen vault üzerinde çalışır.

DeepTutor, yükleme veya dizin yerine bir işaretçi oluşturur. Markdown notlarını tanır, vault bağlantılarını ve etiketlerini izler, `.obsidian`, `.trash` ve `.git` iç dizinlerini yok sayar. Yazmalar eklemelidir: notlar oluşturulabilir, sonuna ekleme yapılabilir veya frontmatter özellikleri verilebilir, ancak asistan mevcut not gövdelerini silmez veya yeniden yazmaz. Bilgi tabanını silmek yalnızca DeepTutor işaretçisini kaldırır; vault'a dokunulmaz.

Kendi kendine barındırılan bir konteyner için, ana makinedeki vault'u aynı yol sunucu konteynerinin içinde de görünecek şekilde bağlayın (mount), ardından sunucu tarafından görülebilen yolu bağlayın. Yalnızca ana makinede geçerli olan bir yol yeterli değildir.

Obsidian notlarının bir kopyası üzerinde anlamsal getirme elde etmek için o kopyayı ayrı, dizinlenmiş bir bilgi tabanı olarak içe aktarın. İki kullanımın net kalması için bağlı vault'u canlı düzenleme amacıyla saklayın.

## Markdown veya Hermes notlarını içe aktarın

Kopyalanmış, dizinlenmiş bir külliyat istiyorsanız bu yolu kullanın. Kaynak notlar özgün konumlarında kalır.

### Web

1. Notları ve varlıkları yerel bir Markdown klasörüne dışa aktarın.
2. DeepTutor'da **Knowledge Center**'ı açın ve **Create KB**'yi seçin.
3. **Create new** ve bir getirme motoru seçin. Varsayılan LlamaIndex'tir; başka bir motoru yalnızca ödünleşimleri külliyata uyduğunda seçin.
4. Dosyaları, bir klasörü veya bir `.zip` arşivini yükleyin.
5. Ayrıştırma ve dizinlemenin bitmesini bekleyin, ardından herhangi bir kaynak yedeğini silmeden önce birkaç temsilî notun getirilebildiğini doğrulayın.

Bir **klasör yüklemesi** göreli dizin yapısını korur. Bir `.zip` arşivi savunmacı biçimde açılır: iç içe dizinler düzleştirilir, desteklenmeyen üyeler atlanır, gizli ve sistem girdileri atlanır ve düzleştirmeden sonra yinelenen dosya adları atlanır. Not başlıkları farklı klasörlerde tekrar ediyorsa veya klasör hiyerarşisi anlamlıysa klasör yüklemesini tercih edin.

Yükleme arayüzü desteklenen uzantıları ve dosya başına sınırı bildirir. Güncel Markdown uzantıları `.md` ve `.markdown`'dır; desteklenen diğer metin, belge, elektronik tablo, sunum, EPUB, görsel ve kaynak kod biçimleri aynı yükleme ilkesiyle kabul edilir.

### CLI

Bir dışa aktarma dizininden:

```bash
deeptutor kb create hermes-notes --docs-dir /path/to/hermes-export
```

Tek bir dosya veya sonraki eklemeler için:

```bash
deeptutor kb create one-note --doc /path/to/note.md
deeptutor kb add hermes-notes --docs-dir /path/to/more-notes
```

CLI, desteklenen dosyaları `--docs-dir` altından özyinelemeli olarak toplar, ardından eşleşen her dosyayı KB'nin `raw/` dizininin en üst düzeyine kopyalar. Yinelenen bir dosya adı daha önceki bir kopyanın üzerine yazabileceğinden, dosya adları tekrar ettiğinde veya hiyerarşi anlamlı olduğunda web klasör yüklemesini tercih edin. Oluşturmayı ve belge sayılarını doğrulamak için `deeptutor kb list` ve `deeptutor kb info hermes-notes` komutlarını kullanın.

## Taşımayı doğrulayın

- Küçük, orta boy ve derinlemesine iç içe bir örnek not açın; metnin, bağlantıların ve varlık başvurularının okunabilir kaldığını kontrol edin.
- Dizinlenmiş bir KB için tam not adları, ifadeler ve kavramlar için temsilî aramalar çalıştırın. Atıf yapılan kaynağın beklenen nota işaret ettiğini doğrulayın.
- Obsidian için bir not arayın, bir bağlantıyı veya geri bağlantıyı izleyin, bir deneme notu oluşturun ve ardından o deneme notunu Obsidian'dan silin.
- Getirme kalitesi ve varlık başvuruları doğrulanana kadar özgün yedeği saklayın.

## Uygulama ve doğrulama

- [deeptutor/capabilities/obsidian/vault.py](../../deeptutor/capabilities/obsidian/vault.py)
- [deeptutor/api/routers/knowledge.py](../../deeptutor/api/routers/knowledge.py)
- [deeptutor_cli/kb.py](../../deeptutor_cli/kb.py)
