import json
import os
import time
from deep_translator import GoogleTranslator

# Ensure the tr directory exists
os.makedirs("web/locales/tr", exist_ok=True)

input_path = "web/locales/en/app.json"
output_path = "web/locales/tr/app.json"

with open(input_path, "r", encoding="utf-8") as f:
    en_data = json.load(f)

# Load existing tr_data if any, to resume
if os.path.exists(output_path):
    with open(output_path, "r", encoding="utf-8") as f:
        tr_data = json.load(f)
else:
    tr_data = {}

translator = GoogleTranslator(source='en', target='tr')

keys = list(en_data.keys())
values = list(en_data.values())

batch_size = 50
print(f"Translating {len(keys)} items in batches of {batch_size}...")

for i in range(0, len(keys), batch_size):
    batch_keys = keys[i:i+batch_size]
    batch_values = [v if v.strip() else " " for v in values[i:i+batch_size]]
    
    # Check if all keys in this batch are already translated
    if all(k in tr_data for k in batch_keys):
        continue
    
    try:
        translated_batch = translator.translate_batch(batch_values)
        for k, v in zip(batch_keys, translated_batch):
            tr_data[k] = v
        
        # Save progress
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(tr_data, f, ensure_ascii=False, indent=2)
            
        print(f"Translated batch {i//batch_size + 1}/{(len(keys) + batch_size - 1)//batch_size}")
        time.sleep(1) # sleep to avoid rate limit
    except Exception as e:
        print(f"Error at batch {i//batch_size + 1}: {e}")
        break

print("Translation complete!")
