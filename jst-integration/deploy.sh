#!/bin/bash
set -e

echo "========================================"
echo "  USTAR 项目 - Docker 一键部署"
echo "========================================"

# 检查 docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    exit 1
fi

# 检查 .env
if [ ! -f .env ]; then
    echo "⚠️  .env 文件不存在，从模板创建..."
    cp .env.example .env
    echo "❗ 请先编辑 .env 填入密钥，然后重新运行"
    exit 1
fi

echo "🔨 构建镜像..."
docker compose build

echo "🚀 启动服务..."
docker compose up -d

echo ""
echo "✅ 部署完成！"
echo ""
echo "📋 运行状态:"
docker compose ps

echo ""
echo "🎯 可用命令:"
echo "  docker compose run --rm app order-push        # 订单推送"
echo "  docker compose run --rm app idcard-upload     # 身份证上传"
echo "  docker compose run --rm app export            # 订单导出"
echo "  docker compose logs -f pdd-cs                 # 查看客服日志"
echo "  docker compose down                           # 停止所有服务"
echo ""
