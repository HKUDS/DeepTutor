import json
import os

os.makedirs("web/locales/tr", exist_ok=True)
input_path = "web/locales/en/app.json"
output_path = "web/locales/tr/app.json"

with open(input_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# Override core keys
overrides = {
    "language.english": "İngilizce",
    "language.chinese": "Çince",
    "language.turkish": "Türkçe",
    "Start": "Başla",
    "Learn": "Öğren",
    "Research": "Araştır",
    "Dashboard": "Kontrol Paneli",
    "Question Generator": "Soru Oluşturucu",
    "Settings": "Ayarlar",
    "Knowledge": "Bilgi Bankası",
    "Memory": "Hafıza",
    "Notebooks": "Not Defterleri",
    "Save": "Kaydet",
    "Cancel": "İptal",
    "Overview": "Genel Bakış",
    "General Settings": "Genel Ayarlar",
    "System Settings": "Sistem Ayarları",
    "Theme": "Tema",
    "Language": "Dil",
    "English": "İngilizce",
    "Chinese": "Çince",
    "Turkish": "Türkçe",
    "Chat": "Sohbet",
    "New Chat": "Yeni Sohbet",
    "Ask anything...": "İstediğini sor...",
    "Deep Research": "Derin Araştırma",
    "Co-Writer": "Yardımcı Yazar"
}

data.update(overrides)

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Fast translation completed.")
