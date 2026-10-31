# Learning Echo eklentisi

[Handbook](../../README.md) · [Eklenti sözleşmesi](../../PLUGINS.md) · [Testler](../../TESTING.md)

Bu paket, yönetilen eklenti çalışma zamanının referans uygulamasıdır.
Bir Araç (Tool), bir Yetenek (Capability), bir HTTP rotası ve bir statik ön yüz
sayfası bildirir. Sayfa yalnızca `sandboxed-iframe` UI iznini ister; paketin
hiçbir Python bağımlılığı yoktur.

## Paket düzeni

- [Manifest](../../../examples/learning_echo/learning_echo/deeptutor.plugin.json): eklenti kimliği, izinler
  ve dört uzantı bildirimi.
- [Worker](../../../examples/learning_echo/learning_echo/worker.py): açıklamalar, araç yürütme, yetenek
  akışı ve JSON HTTP yanıtları.
- [Sayfa manifesti](../../../examples/learning_echo/learning_echo/frontend/page.json): açıkça belirtilmiş statik varlık
  kümesi; [index.html](../../../examples/learning_echo/learning_echo/frontend/index.html) ve
  [app.js](../../../examples/learning_echo/learning_echo/frontend/app.js) sandbox içindeki sayfayı uygular.
- [Derleme meta verileri](../../../examples/learning_echo/pyproject.toml): worker'ı, manifesti ve varlıkları paketler.

## Derleme ve inceleme

Depo kök dizininden yerel bir wheel derleyin:

```bash
python -m pip wheel --no-deps -w /tmp/deeptutor-plugins docs-for-dev/examples/learning_echo
```

Tek kullanımlık bir `DEEPTUTOR_HOME` kullanın, ardından üretilen wheel yoluyla
`deeptutor plugin install` komutunu çalıştırın ve şunlarla inceleyin:

```bash
deeptutor plugin show org.deeptutor.learning_echo
deeptutor plugin state
```

`deeptutor plugin approve org.deeptutor.learning_echo` komutunu çağırmadan önce manifesti ve yapıtı
gözden geçirin; devre dışıysa eklentiyi açıkça etkinleştirin. Kurulu ve onaylı durumları
birbirinden farklıdır. Kurulum adımı, eklenti kodunu içe aktarmadan önce `deeptutor.plugin.json`
dosyasını okur ve eklentiye özel bir sanal ortam oluşturur.

Onay ve etkinleştirmeden sonra sayfa
`/api/plugins/org.deeptutor.learning_echo/pages/learning_echo_page/` adresinde kullanılabilir. Giriş noktası ve
varlık kümesi `learning_echo/frontend/page.json` içinde bildirilir.

Ana makine kimlik doğrulaması etkinken, sayfayı veya `public` HTTP rotasını açmak
yine de ana makine oturumunu gerektirir. Sayfanın CSP'si rastgele ağ
erişimini engeller; bu, ana makine ön yüz koduna enjeksiyon yapmanın bir örneği değildir.

## Doğrulama ve uyarlama

Depo kök dizininden:

```bash
python -m pytest tests/plugins/test_runtime.py tests/api/test_plugins_router.py
```

Bu testler, bu paketi worker/sayfa fixture'ı olarak kullanır. Örneği taşırken veya değiştirirken
testleri koruyun. Yeni bir eklenti için ayrı bir
paket/manifest kimliği seçin, gerçek izin ve bağımlılık
kümesini bildirin; hata, iptal, devre dışı durum ve yükseltmeden sonra yeniden onayı test edin.
Güven sınırları ve geri alma davranışı için [eklenti kılavuzuna](../../PLUGINS.md) bakın.
