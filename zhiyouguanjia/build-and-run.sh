#!/bin/bash
# ===================================================
# 直邮管家 ZYGJ — Docker 构建+启动
# ===================================================
# 用法：
#   ssh ustar@192.168.178.26
#   cd /opt/data/workspace/zhiyouguanjia
#   bash build-and-run.sh
#
# 容器: zhiyouguanjia
# 端口: 8899
# ===================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE_NAME="zygj:latest"
CONTAINER_NAME="zhiyouguanjia"

echo "📦 直邮管家 ZYGJ Docker 构建"
echo "========================================"
echo ""

# 检查 .env
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "⚠️  .env 文件不存在，从 .env.example 复制..."
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    echo "   请编辑 .env 填入 JST_APP_KEY / JST_APP_SECRET / JST_TOKEN"
    echo "   然后重新执行此脚本"
    exit 1
fi

# 1. 构建镜像
echo "🔨 [1/3] 构建 Docker 镜像: ${IMAGE_NAME}..."
docker build -t "${IMAGE_NAME}" "$SCRIPT_DIR"

# 2. 停掉旧容器
echo ""
echo "🛑 [2/3] 停掉旧容器..."
docker stop "${CONTAINER_NAME}" 2>/dev/null || true
docker rm "${CONTAINER_NAME}" 2>/dev/null || true

# 3. 启动新容器
echo ""
echo "🚀 [3/3] 启动新容器..."
docker compose up -d

# 验证
sleep 3
echo ""
if docker ps --format '{{.Names}}' | grep -q "${CONTAINER_NAME}"; then
    echo "✅ ${IMAGE_NAME} 已成功启动!"
    echo "   本地: http://127.0.0.1:8899"
    echo "   日志: docker logs -f ${CONTAINER_NAME}"
    echo "   重启: docker restart ${CONTAINER_NAME}"
else
    echo "❌ 启动失败！检查日志: docker logs ${CONTAINER_NAME}"
fi
echo "========================================"
