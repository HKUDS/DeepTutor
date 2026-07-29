#!/bin/bash
# ============================================
# MathTutor — MathNet 题库一键同步
# 从云端 mathnet-kb 拉取 13k+ 竞赛题并建立本地 RAG 索引
# ============================================
set -e

cd "$(dirname "$0")/.."

CLOUD_URL="${MATHNET_CLOUD_URL:-http://8.138.199.23:8080}"
BACKEND="${BACKEND_URL:-http://localhost:8002}"

echo "╔══════════════════════════════════════╗"
echo "║   MathNet 题库同步                   ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "云端服务器: ${CLOUD_URL}"
echo "本地后端:   ${BACKEND}"
echo ""

# 检查后端是否在线
if ! curl -s -o /dev/null "${BACKEND}/api/v1/mathnet/health" 2>/dev/null; then
    echo "错误: 后端未运行，请先执行 ./scripts/start.sh"
    exit 1
fi

echo "正在从云端下载题库 Markdown 并建立索引..."
echo "（首次同步 13k 题预计需要 30-60 分钟，取决于网络与 embedding 速度）"
echo ""

HTTP_CODE=$(curl -s -o /tmp/mathnet-sync-response.json -w "%{http_code}" \
    -X POST "${BACKEND}/api/v1/knowledge/sync-mathnet" \
    -H "Content-Type: application/json" \
    -d "{\"cloud_url\": \"${CLOUD_URL}\"}")

if [ "$HTTP_CODE" = "200" ]; then
    TASK_ID=$(python3 -c "import json; print(json.load(open('/tmp/mathnet-sync-response.json')).get('task_id', ''))" 2>/dev/null || echo "")
    echo ""
    echo "✓ 同步任务已提交，正在后台处理中..."
    if [ -n "$TASK_ID" ]; then
        echo "  任务 ID: ${TASK_ID}"
    fi
    echo ""
    echo "你可以在 Settings → Knowledge Bases 中查看 MathNet KB 的索引进度。"
    echo "索引完成后，在 Chat 中选择 MathNet 知识库即可开始提问。"
elif [ "$HTTP_CODE" = "400" ]; then
    echo "错误: 请求参数有误，请检查 MATHNET_CLOUD_URL"
    cat /tmp/mathnet-sync-response.json 2>/dev/null
    exit 1
else
    echo "错误: 同步失败 (HTTP ${HTTP_CODE})"
    cat /tmp/mathnet-sync-response.json 2>/dev/null
    exit 1
fi

rm -f /tmp/mathnet-sync-response.json
