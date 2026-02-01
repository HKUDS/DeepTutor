# Performance Optimization Guide

## Current Issue: High CPU Usage (1696% = ~17 cores)

The Docker container is using excessive CPU resources, causing slowdowns.

## Root Causes

1. **Docling Parser is CPU-Intensive**
   - PDF parsing, OCR, layout analysis
   - No concurrency limits
   - Processes multiple files simultaneously

2. **No Docker Resource Limits**
   - Container can use all available CPUs
   - No memory limits
   - Causes system slowdown

3. **Multiple Processes Running**
   - 243 PIDs in container
   - Background tasks competing for resources

## Solutions Applied

### 1. Docker Resource Limits (docker-compose.yml)

Added CPU and memory limits:
```yaml
deploy:
  resources:
    limits:
      cpus: '8'           # Max 8 CPUs
      memory: 12G         # Max 12GB RAM
    reservations:
      cpus: '2'           # Min 2 CPUs
      memory: 4G          # Min 4GB RAM
```

**To apply:**
```bash
docker compose down
docker compose up -d
```

### 2. Process Files Sequentially

Files are already processed one at a time (see `add_documents.py:531`), but Docling parser itself uses multiple threads internally.

### 3. Monitor Resource Usage

```bash
# Watch Docker stats
docker stats deeptutor

# Check container limits
docker inspect deeptutor | grep -A 10 "Resources"
```

## Additional Optimizations

### Option 1: Reduce CPU Limit (If Still Too High)

Edit `docker-compose.yml`:
```yaml
deploy:
  resources:
    limits:
      cpus: '4'           # Reduce to 4 CPUs
      memory: 8G
```

### Option 2: Process Fewer Files at Once

Currently processes 1 file at a time. If you want to batch process, you can modify the code, but sequential is recommended for stability.

### Option 3: Use MinerU Instead of Docling (Faster)

MinerU parser is generally faster than Docling:
- Switch KB metadata to `"rag_provider": "raganything"`
- Trade-off: Docling has better table/layout parsing

### Option 4: Increase Docker Desktop Resources

In Docker Desktop → Settings → Resources:
- CPUs: Set to match your system (e.g., 8-12)
- Memory: Set to 16GB+ if available
- Apply & Restart

## Expected Results

After applying resource limits:
- **CPU Usage**: Should drop to ~400-800% (4-8 cores)
- **Performance**: Slightly slower but more stable
- **System**: Won't freeze or slow down your Mac

## Monitoring

```bash
# Real-time monitoring
watch -n 2 'docker stats --no-stream deeptutor'

# Check if limits are applied
docker inspect deeptutor | grep -A 15 "Resources"
```

## Troubleshooting

If container is too slow after limits:
1. Increase CPU limit to 6-8 CPUs
2. Ensure Docker Desktop has enough resources allocated
3. Close other resource-intensive applications

If container crashes:
1. Increase memory limit
2. Check logs: `docker compose logs deeptutor`
3. Reduce concurrent operations
