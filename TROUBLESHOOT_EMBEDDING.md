# Knowledge Base Embedding Process - Troubleshooting Options

## Current Situation
- **Process Status**: Running but appears stuck
- **Knowledge Base**: Mathmatics
- **Progress**: 0/27 documents (0%)
- **Last Update**: Yesterday (stale progress file)

---

## Available Options

### Option 1: Monitor the Process (Recommended First Step)
Check if the process is actually making progress:

```bash
# Watch Docker logs in real-time
cd /Users/anup.singh/Documents/Deeptutor/DeepTutor
docker compose logs -f deeptutor

# Or check recent logs for errors
docker compose logs --tail=100 deeptutor | grep -i "error\|fail\|Mathmatics"
```

**What to look for:**
- Embedding API calls
- Document processing messages
- Error messages
- Timeout warnings

---

### Option 2: Kill the Stuck Process
If the process is truly stuck, kill it:

```bash
# Method 1: Kill by process ID
kill 57432 57430 57418

# Method 2: Kill by pattern (more thorough)
pkill -f "docker compose exec.*DocumentAdder"
pkill -f "docker compose exec.*add_documents"

# Method 3: Use the provided script
chmod +x kill_stuck_process.sh
./kill_stuck_process.sh
```

**After killing:**
- Clear the progress file (see Option 3)
- Restart the process (see Option 4)

---

### Option 3: Clear Progress File
Clear the stale progress file to reset the status:

**Via API:**
```bash
curl -X POST http://localhost:8001/api/v1/knowledge/Mathmatics/progress/clear
```

**Via File System:**
```bash
rm /Users/anup.singh/Documents/Deeptutor/DeepTutor/data/knowledge_bases/Mathmatics/.progress.json
```

**Via Docker:**
```bash
docker compose exec deeptutor rm /app/data/knowledge_bases/Mathmatics/.progress.json
```

---

### Option 4: Restart the Processing
After clearing progress, restart the embedding process:

**Via Web UI:**
1. Go to `http://localhost:3782/knowledge`
2. Find "Mathmatics" knowledge base
3. Click "Process" or "Initialize" button

**Via Command Line:**
```bash
docker compose exec deeptutor python3 -c "
import sys
sys.path.insert(0, '/app')
from pathlib import Path
import asyncio
from src.knowledge.add_documents import DocumentAdder
from src.services.llm import get_llm_config

# Get missing files
raw_dir = Path('/app/data/knowledge_bases/Mathmatics/raw')
content_list_dir = Path('/app/data/knowledge_bases/Mathmatics/content_list')

processed = set(f.stem for f in content_list_dir.glob('*.json') if f.is_file())
all_pdfs = [f for f in raw_dir.glob('*.pdf') if f.is_file()]
missing = [f for f in all_pdfs if f.stem not in processed]

if missing:
    llm_config = get_llm_config()
    adder = DocumentAdder(
        kb_name='Mathmatics',
        base_dir='/app/data/knowledge_bases',
        api_key=llm_config.api_key,
        base_url=llm_config.base_url,
        rag_provider='raganything_docling'
    )
    
    file_paths = [str(f) for f in missing]
    print(f'Processing {len(file_paths)} files...')
    
    async def process():
        staged = adder.add_documents(file_paths, allow_duplicates=False)
        if staged:
            processed_files = await adder.process_new_documents(staged)
            if processed_files:
                adder.extract_numbered_items_for_new_docs(processed_files)
                adder.update_metadata(len(processed_files))
                print(f'✅ Successfully processed {len(processed_files)} files')
            else:
                print('⚠️ No files were processed')
        else:
            print('⚠️ No files to stage')
    
    asyncio.run(process())
else:
    print('✅ All files already processed')
"
```

---

### Option 5: Check System Status
Verify that embedding service is working:

**Check Embedding API Status:**
```bash
# Test embedding connection
curl -X POST http://localhost:8001/api/v1/system/test/embeddings

# Check system status
curl http://localhost:8001/api/v1/system/status
```

**Check Docker Container:**
```bash
docker compose ps
docker compose exec deeptutor python3 -c "
from src.services.embedding import get_embedding_client, get_embedding_config
import asyncio

async def test():
    try:
        config = get_embedding_config()
        client = get_embedding_client()
        print(f'Embedding Model: {config.model}')
        print(f'Provider: {config.binding}')
        result = await client.embed(['test'])
        print(f'✅ Embedding service working! Vector size: {len(result[0])}')
    except Exception as e:
        print(f'❌ Error: {e}')

asyncio.run(test())
"
```

---

### Option 6: Check Resource Usage
Verify system resources aren't exhausted:

```bash
# Check Docker container resources
docker stats deeptutor

# Check disk space
df -h
docker system df

# Check memory
docker compose exec deeptutor free -h 2>/dev/null || docker compose exec deeptutor cat /proc/meminfo | head -5
```

---

### Option 7: Wait and Monitor
If the process is just slow (not stuck), you can wait:

**Monitor progress via WebSocket:**
- Open browser console on knowledge page
- Progress updates come via WebSocket every few seconds

**Check progress file periodically:**
```bash
watch -n 5 'cat /Users/anup.singh/Documents/Deeptutor/DeepTutor/data/knowledge_bases/Mathmatics/.progress.json'
```

---

## Recommended Action Plan

1. **First**: Monitor logs (Option 1) for 2-3 minutes to see if there's any activity
2. **If stuck**: Kill process (Option 2) → Clear progress (Option 3) → Restart (Option 4)
3. **If slow**: Check system status (Option 5) and resources (Option 6)
4. **If working**: Just wait and monitor (Option 7)

---

## Quick Fix Script

Run this to kill stuck process, clear progress, and check status:

```bash
#!/bin/bash
cd /Users/anup.singh/Documents/Deeptutor/DeepTutor

echo "1. Killing stuck processes..."
pkill -f "docker compose exec.*DocumentAdder" 2>/dev/null
sleep 2

echo "2. Clearing progress file..."
docker compose exec -T deeptutor rm -f /app/data/knowledge_bases/Mathmatics/.progress.json 2>/dev/null

echo "3. Checking embedding service..."
docker compose exec -T deeptutor python3 -c "
from src.services.embedding import get_embedding_client, get_embedding_config
import asyncio

async def test():
    try:
        config = get_embedding_config()
        client = get_embedding_client()
        result = await client.embed(['test'])
        print(f'✅ Embedding OK: {config.model} ({len(result[0])}D)')
    except Exception as e:
        print(f'❌ Embedding Error: {e}')

asyncio.run(test())
"

echo "4. Done! You can now restart processing via web UI or command line."
```

---

## Need More Help?

- Check logs: `docker compose logs deeptutor`
- Check API docs: `http://localhost:8001/docs`
- Check web UI: `http://localhost:3782/knowledge`
