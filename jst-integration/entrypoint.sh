#!/bin/bash
set -e

cd /app/app/ustar_jst

show_help() {
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║        USTAR 跨境电商ERP工具集               ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""
    echo "可用命令:"
    echo ""
    echo "  order-push          运行订单推送系统 (交互式)"
    echo "  order-push-batch    运行批量订单推送"
    echo "  idcard-upload       运行身份证上传"
    echo "  idcard-batch        批量处理身份证"
    echo "  export              导出订单"
    echo "  bash                进入 Shell"
    echo ""
    echo "环境变量:"
    echo "  JST_APP_KEY         聚水潭 App Key"
    echo "  JST_APP_SECRET     聚水潭 App Secret"
    echo "  JST_TOKEN          聚水潭 Token"
    echo "  DEEPSEEK_API_KEY    DeepSeek API Key"
    echo "  QWEN_API_KEY       千问 API Key"
    echo ""
}

case "${1:-help}" in
    order-push)
        echo "🚀 启动聚水潭订单推送系统..."
        exec python workflows/order_push_flow.py
        ;;
    order-push-batch)
        echo "📦 启动批量订单推送..."
        exec python jst_push.py
        ;;
    idcard-upload)
        echo "🪪 启动身份证上传..."
        exec python 身份证上传/upload_idcard.py
        ;;
    idcard-batch)
        echo "🪪 批量处理身份证..."
        exec python 身份证上传/idcard_workflow_v3.py
        ;;
    export)
        echo "📊 导出订单..."
        exec python 订单导出/export_template.py
        ;;
    bash|shell)
        shift
        exec bash "$@"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "❌ 未知命令: $1"
        show_help
        exit 1
        ;;
esac
