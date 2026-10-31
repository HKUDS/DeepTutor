# Çalışma alanı olarak bir sunucu klasörü seçme

Yeni bir sohbette, yazma alanının yanındaki çalışma alanı menüsünü açın ve
**Choose a server folder** seçeneğini seçin. İstediğiniz proje görüntülenene kadar
klasörleri açın, ardından **Select this folder** seçeneğini seçin. Yeni kayıtlar
klasör adını kullanır; mevcut kayıtlar adlarını ve ayarlarını korur. Arşivlenmiş
bir kaydı seçmek onu geri yükler. Mesajları olan sohbetler mevcut bağlarını korur.

Aynı seçici **Settings → Workspaces → New workspace** içinde de bulunur; orada
mevcut klasör yolunu ve varsayılan bir çalışma alanı adını doldurur. Klasörlere
göz atma salt okunurdur. Kayıt, mevcut çalışma alanı doğrulamasını ve çıktı
dizini başlatmasını kullanmaya devam eder.

## Dağıtım

Seçici, tarayıcıyı çalıştıran bilgisayarın değil, arka ucun dosya sistemine göz
atar. Docker'da proje klasörleri önce bind mount ile bağlanmalıdır. Örneğin
`/srv/projects` dizinini konteyner içinde `/srv/projects` olarak bağlayın ve
`DEEPTUTOR_WORKSPACE_BROWSER_ROOTS=/srv/projects` değerini ayarlayın.

Birden fazla kök, arka uç platformunun yol ayırıcısıyla ayrılır (Linux/macOS'ta
`:`, Windows'ta `;`). Bu ayar yoksa seçici, içerik çalışma alanı politikasının
zaten sağladığı kökleri kullanır. Yapılandırılan kökler, istek yapan kullanıcı
için bu politikaya göre de denetlenir; bu ayar yönetici olmayan bir kullanıcıya
ek klasörlere erişim vermez. Yöneticiler de seçicinin yapılandırılmış göz atma
kökleriyle sınırlı kalır.

Seçici, erişilebilir gizli olmayan alt dizinleri gösterir ve geçerli kökün
dışına çözümlenen sembolik bağlantıları atlar. Her dizin taraması 10.000 girdiyle
sınırlıdır ve en fazla 500 klasör döndürür. Filtreleme, tüm proje ağacında özyinelemeli
olarak değil, görüntülenen dizinde uygulanır. API `GET /api/settings/workspace/folders?path=...`
biçimindedir ve ayar kimlik doğrulamasını devralır.
