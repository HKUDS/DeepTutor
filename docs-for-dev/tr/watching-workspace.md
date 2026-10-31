# Immersive Reading'de video ile öğrenme

[El kitabı](README.md) · [İlgili kılavuz](READING_EXTENSIONS.md)

Learning altındaki **Reading** bölümünü açın, bir koleksiyona YouTube veya Bilibili URL'si ekleyin ve videoyu eğitmenin yanında çalışın. Videolar, belgelerle aynı okuma materyali, transkript, not ve konuşma depolarını kullanır. Medya aşaması transkript araması ve takibini, zaman damgası atıflarını, tam ekran izlemeyi ve mevcut/sonraki altyazı satırlarını destekler. Eksik altyazılar veya desteklenmeyen oynatma açıkça gösterilir; bir eğitmen yalnızca transkript metninden yola çıkarak görüntüleri izlediğini iddia etmemelidir.

Zaman damgalı yeni notlar Reading notlarıdır. Konumları editör açıldığında yakalanır; bu nedenle siz yazarken oynatmanın ilerlemesi notu taşımaz. Başarısız kayıtlarda taslak, yeniden deneme için korunur; daha eski bir kaydın sonradan tamamlanması daha yeni metni silmez.

## Mevcut Watching konuşmaları

Bağımsız Watching kullanımdan kaldırılmıştır. Mevcut `/watching/{sessionId}` ve `/learning/watching/{sessionId}` bağlantıları, konuşmayı açıkça Reading'e taşıyan bir uyumluluk rotasını açar. Konuşma kimliği ve mesajlar aynı kalır. Eski video JSON'u bir sağlayıcı/önbellek kaydı olarak durur; mevcut **Video Learning** not defteri kayıtları okunabilir kalır ve yeniden yazılmaz. Uyumlu transkriptler, notlar ve kaydedilmiş konumlar Reading'e idempotent biçimde kopyalanır; mevcut bir Reading konumu, daha eski bir içe aktarılmış konumdan önceliklidir.

Oturum listeleme ve inceleme materyal oluşturmaz. Taşıma, öğrenci eski konuşmayı açtığında veya eski bir turu sürdürdüğünde gerçekleşir. Eski video önbelleği eksikse, konuşma kullanılamayan video durumu kaydedilerek sıradan bir sohbet olarak erişilebilir kalır; başka bir video asla sessizce yerine konmaz. Diğer taşıma hatalarında özgün tercihler korunur ve yeniden deneme sunulur.

## Invidious yapılandırması

Yönetici ayarlarında video öğrenme ayarlarını açın, Invidious örneğinin backend API origin'ini ve genel origin'ini girin, bağlantıyı test edin ve varsayılan sağlayıcı olarak Invidious'u seçin. Reading'in YouTube altyazı yükleyicisi bu yapılandırılmış sağlayıcıyı kullanır. Bilibili bağımsız kalır. Kullanılamayan bir altyazı hizmeti, yerel olarak oynatılabilen bir videoyu kullanılamaz hale getirmez; ancak eksik transkript görünür olur ve eğitmenin kanıtı sınırlı kalır.

`invidious.api_base_url` backend tarafından erişilebilir olmalıdır; `invidious.public_base_url` tarayıcı tarafından erişilebilir olmalıdır. Özel HTTP origin'leri, mevcut yapılandırılmış örnek politikası kapsamında loopback, LAN veya overlay adreslerini kullanabilir. Genel örnekler HTTPS gerektirir. Ayarları `video_learning.json` içinde tutun; proje `.env` dosyaları yok sayılır.

Bir hesabın aboneliklerinden ve oynatma listelerinden arama yapmak veya seçim yapmak için materyal ekleme iletişim kutusundaki **Browse Invidious** seçeneğini kullanın. Hesap belirteçleri yalnızca sahibine özel kalır. `GET:feed`, `GET:playlists` ve `GET:playlists/*` yetkileri olmayan eski belirteçler yeniden bağlantı gerektirir; hiçbir abonelik veya oynatma listesi değişikliği istenmez. DeepTutor, Invidious parolasını asla istemez. Yetkilendirme yapılandırılmış örnek üzerinde gerçekleşir ve geri çağrı geri bildirimi, yönlendirme hedefine bir belirteç koymadan Reading'e döner. Bağlantıyı kesme başarısız olursa belirteç yeniden deneme için korunur.

## Doğrulama ve kurtarma

Oynatmayı, ileri/geri sarmayı, transkript arama/takibini, zaman damgası atıflarını ve not kaydetme/düzenleme/yeniden denemeyi kontrol edin. Taşınmış bir konuşmayı yeniden açın ve mesaj geçmişinin ile kaynak kimliğinin değişmediğini doğrulayın. Ayrıca eksik altyazıları, kullanılamayan bir sağlayıcıyı, dar ekranları ve sahip erişim sınırlarını kontrol edin. Dağıtım veya geri alma sırasında mevcut veri dizinini ve sahip kimliğini koruyun; yalnızca bir frontend değişikliğini geri almak için daha yeni kullanıcı verilerinin üzerine bir yedek yazmayın.

## Uygulama ve doğrulama

- [deeptutor/reading/](../../deeptutor/reading/)
- [web/components/reading/](../../web/components/reading/)
