#!/bin/bash
# ==========================================
# USTAR 项目 - 一键部署脚本
# SSH 到绿联 NAS 后执行：
#   bash /volume1/docker/openclaw1/ustar-deploy/setup.sh
# ==========================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="/volume1/docker/ustar"

echo "========================================"
echo "  USTAR 项目部署"
echo "========================================"
echo "源目录: $SCRIPT_DIR"
echo "目标目录: $TARGET_DIR"
echo ""

# 1. 创建目标目录
if [ ! -d "$TARGET_DIR" ]; then
    echo "📁 创建目录 $TARGET_DIR ..."
    mkdir -p "$TARGET_DIR"
fi

# 2. 复制部署文件（排除 .env 避免覆盖已有配置）
echo "📦 复制部署文件..."
cp -r "$SCRIPT_DIR"/.env "$TARGET_DIR/" 2>/dev/null || true
cp -r "$SCRIPT_DIR"/.env.example "$TARGET_DIR/" 2>/dev/null || true
cp -r "$SCRIPT_DIR"/.dockerignore "$TARGET_DIR/" 2>/dev/null || true
cp "$SCRIPT_DIR"/docker-compose.yml "$TARGET_DIR/"
cp "$SCRIPT_DIR"/Dockerfile "$TARGET_DIR/"
cp "$SCRIPT_DIR"/entrypoint.sh "$TARGET_DIR/"
cp "$SCRIPT_DIR"/requirements.txt "$TARGET_DIR/"
cp -r "$SCRIPT_DIR"/app "$TARGET_DIR/"
chmod +x "$TARGET_DIR"/entrypoint.sh

cd "$TARGET_DIR"

# 3. 检查 .env
if [ ! -f .env ]; then
    echo "⚠️  未找到 .env，从模板创建..."
    cp .env.example .env
    echo "❗ 请先编辑 .env 填入 PDD_API 密钥，然后重新运行"
    echo "   nano .env"
    exit 1
fi

# 4. 构建镜像
echo "🔨 构建 Docker 镜像..."
docker compose build

# 5. 启动服务
echo "🚀 启动服务..."
docker compose up -d

echo ""
echo "========================================"
echo "  ✅ USTAR 项目部署完成！"
echo "========================================"
echo ""
docker compose ps

echo ""
echo "🎯 可用命令:"
echo ""
echo "  订单推送 (交互式):"
echo "    docker compose run --rm app order-push"
echo ""
echo "  身份证上传:"
echo "    docker compose run --rm app idcard-upload"
echo ""
echo "  导出订单:"
echo "    docker compose run --rm app export"
echo ""
echo "  拼多多客服 (后台运行中):"
echo "    docker compose logs -f pdd-cs"
echo ""
echo "  停止服务:"
echo "    docker compose down"
echo ""
