#!/bin/bash
# Quick fix for stuck knowledge base embedding process

cd /Users/anup.singh/Documents/Deeptutor/DeepTutor

echo "=========================================="
echo "Knowledge Base Embedding - Quick Fix"
echo "=========================================="
echo ""

echo "Step 1: Checking for stuck processes..."
PROCESSES=$(ps aux | grep -E "docker compose exec.*DocumentAdder|docker compose exec.*add_documents" | grep -v grep | wc -l)
if [ "$PROCESSES" -gt 0 ]; then
    echo "   Found $PROCESSES stuck process(es). Killing..."
    pkill -f "docker compose exec.*DocumentAdder" 2>/dev/null
    pkill -f "docker compose exec.*add_documents" 2>/dev/null
    sleep 2
    echo "   ✅ Processes killed"
else
    echo "   ✅ No stuck processes found"
fi

echo ""
echo "Step 2: Clearing stale progress file..."
docker compose exec -T deeptutor rm -f /app/data/knowledge_bases/Mathmatics/.progress.json 2>/dev/null
if [ $? -eq 0 ]; then
    echo "   ✅ Progress file cleared"
else
    echo "   ⚠️  Could not clear progress file (may not exist)"
fi

echo ""
echo "Step 3: Testing embedding service..."
docker compose exec -T deeptutor python3 -c "
from src.services.embedding import get_embedding_client, get_embedding_config
import asyncio

async def test():
    try:
        config = get_embedding_config()
        client = get_embedding_client()
        result = await client.embed(['test'])
        print(f'   ✅ Embedding service OK')
        print(f'   Model: {config.model}')
        print(f'   Provider: {config.binding}')
        print(f'   Vector dimension: {len(result[0])}')
    except Exception as e:
        print(f'   ❌ Embedding service ERROR: {e}')

asyncio.run(test())
" 2>&1 | sed 's/^/   /'

echo ""
echo "Step 4: Checking Docker container status..."
docker compose ps deeptutor

echo ""
echo "=========================================="
echo "Next Steps:"
echo "=========================================="
echo "1. Monitor logs: docker compose logs -f deeptutor"
echo "2. Restart processing via web UI: http://localhost:3782/knowledge"
echo "3. Or use the command line script (see TROUBLESHOOT_EMBEDDING.md)"
echo ""
echo "Done!"
