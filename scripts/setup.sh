#!/bin/bash
# ============================================
# MathTutor — 学生一键安装脚本
# 适用于 macOS 和 Linux
# ============================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   MathTutor 竞赛数学 AI 导师 — 安装  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""

# --- 检查 Python ---
echo "1/5  检查 Python 3.11+ ..."
PYTHON=""
for cmd in python3.11 python3.12 python3.13 python3; do
    if command -v "$cmd" &> /dev/null; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        MAJOR=$("$cmd" -c "import sys; print(sys.version_info.major)")
        MINOR=$("$cmd" -c "import sys; print(sys.version_info.minor)")
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 11 ]; then
            PYTHON="$cmd"
            echo "   ✓ 找到 $PYTHON (版本 $VER)"
            break
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    echo -e "${RED}   错误: 需要 Python 3.11 或更高版本${NC}"
    echo "   macOS: brew install python@3.12"
    echo "   Ubuntu/Debian: sudo apt install python3.12 python3.12-venv"
    echo "   或从 https://www.python.org/downloads/ 下载安装"
    exit 1
fi

# --- 检查 Node.js ---
echo "2/5  检查 Node.js 22+ ..."
if ! command -v node &> /dev/null; then
    echo -e "${RED}   错误: 需要 Node.js${NC}"
    echo "   macOS: brew install node"
    echo "   或从 https://nodejs.org 下载安装"
    exit 1
fi
NODE_VER=$(node --version | sed 's/v//' | cut -d. -f1)
if [ "$NODE_VER" -lt 22 ]; then
    echo -e "${YELLOW}   ⚠ Node $(node --version) 较旧，建议升级到 22+${NC}"
fi
echo "   ✓ Node $(node --version)"

# --- 创建 Python 虚拟环境 ---
echo "3/5  创建 Python 虚拟环境 ..."
if [ ! -d ".venv" ]; then
    "$PYTHON" -m venv .venv
    echo "   ✓ .venv 创建成功"
else
    echo "   .venv 已存在，跳过"
fi

# --- 安装 Python 依赖 ---
echo "4/5  安装 Python 依赖（需要 1-2 分钟）..."
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements/server.txt
echo "   ✓ Python 依赖安装完成"

# --- 安装前端依赖并构建 ---
echo "5/5  安装前端依赖并构建（需要 2-3 分钟）..."
cd web
NODE_OPTIONS="--max-old-space-size=4096" npm ci --silent 2>&1 | tail -1
NODE_OPTIONS="--max-old-space-size=4096" npm run build --silent 2>&1 | tail -1
cd ..
echo "   ✓ 前端构建完成"

# --- 生成 .env ---
if [ ! -f ".env" ]; then
    cp .env.student .env
    echo ""
    echo -e "${YELLOW}  ╔════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}  ║  ⚠ 请编辑 .env 文件填入你的 API Key：      ║${NC}"
    echo -e "${YELLOW}  ║                                            ║${NC}"
    echo -e "${YELLOW}  ║  LLM_API_KEY=          DeepSeek API Key     ║${NC}"
    echo -e "${YELLOW}  ║  EMBEDDING_API_KEY=    SiliconFlow API Key  ║${NC}"
    echo -e "${YELLOW}  ║                                            ║${NC}"
    echo -e "${YELLOW}  ║  获取方式见 README_STUDENT.md              ║${NC}"
    echo -e "${YELLOW}  ╚════════════════════════════════════════════╝${NC}"
fi

echo ""
echo -e "${GREEN}  ✓ 安装完成！${NC}"
echo ""
echo "  下一步："
echo "  1. 编辑 .env 填入你的 DeepSeek API Key"
echo "  2. 运行 ./scripts/start.sh 启动 MathTutor"
echo "  3. 浏览器打开 http://localhost:3782"
echo "  4. 运行 ./scripts/sync-mathnet.sh 同步题库"
echo ""
