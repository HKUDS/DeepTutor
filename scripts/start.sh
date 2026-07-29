#!/bin/bash
# ============================================
# MathTutor — 启动脚本
# 运行前请确保已执行过 setup.sh 并编辑了 .env
# ============================================
set -e

cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
    echo "错误: 未找到 .venv，请先运行 ./scripts/setup.sh"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "错误: 未找到 .env，请先运行 ./scripts/setup.sh"
    exit 1
fi

source .venv/bin/activate
echo "正在启动 MathTutor ..."
echo "  后端: http://localhost:8002"
echo "  前端: http://localhost:3782 (在这里使用)"
echo ""
python scripts/start_web.py
