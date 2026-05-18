# ESYGJST — ECShop + 阳光之路 + 聚水潭 整合系统

> ECShop 电商平台 AI 智能体 + 聚水潭 ERP 全链路集成 + 货易达物流同步

## 📋 目录结构

```
ESYGJST/
├── ecshop-agent/          # ECShop AI Agent — FastAPI 购物助手
│   ├── agent_service.py   # Agent 主服务（对话式下单、支付、查订单）
│   ├── ecshop_client.py   # ECShop/Appserver API 客户端
│   ├── fix_nginx_proxy.py # nginx /agent-api/ 代理修复脚本
│   ├── entrypoint.sh      # Docker 容器启动入口
│   └── ...
├── ecshop-h5/             # H5 购物小助手前端方案文档
├── jst-integration/       # 聚水潭 ERP 集成（核心项目）
│   ├── docker-compose.yml # 容器编排
│   ├── Dockerfile         # 构建文件
│   ├── setup.sh           # 部署脚本
│   ├── requirements.txt   # Python 依赖
│   └── app/ustar_jst/     # JST 业务代码
│       ├── core/          # API 客户端（JST、快递100）
│       ├── domains/       # 业务域：订单/商品/售后/查询
│       ├── parser/        # 订单解析 & SKU 映射
│       ├── workflows/     # 工作流：订单推送/库存同步/日报
│       ├── cli/           # CLI 工具
│       └── bots/          # Telegram 机器人
├── heute-express/         # 货易达物流同步系统
│   ├── heute_express_sync.py  # 主同步脚本
│   ├── heute_sdk.py           # 货易达 API SDK
│   ├── heute_cli.py           # CLI 接口
│   ├── batch_track.py         # 批量物流查询
│   ├── scan_anomalies.py      # 异常订单扫描
│   └── data/                  # 数据库 & 缓存
├── idcard-auth/           # 身份证认证系统
│   ├── auth_system.py     # 认证服务
│   ├── idcard_cli.py      # CLI 接口
│   └── image_processor.py # 图片处理
└── docs/                  # 文档
    └── 阳光之路-PM架构.md # 阳光之路产品架构
```

## 🚀 核心功能

### 🤖 ECShop AI Agent
- **对话式购物** — 搜索商品、加购、下单、支付，全程对话完成
- **智能意图识别** — 支持搜索、分类浏览、热销排行、排序
- **余额支付** — 自动扣余额、改状态、发通知
- **H5 购物小助手** — 浮动按钮 + 对话面板 + 语音输入

### 🔄 聚水潭 ERP 集成
- **订单推送** — 自动推送 ECShop 订单到 JST
- **库存同步** — 定时从 JST 同步库存到 ECShop（支持多规格）
- **身份证认证** — OCR 识别 + 自动上传 JST
- **卖家备注** — 自动写入物流单号
- **地址更新** — 通过 API 更新订单地址

### 📦 货易达物流同步
- **自动同步** — 定时拉取货易达订单到本地数据库
- **物流查询** — 快递100 多源物流轨迹查询
- **卖家备注写入** — 自动将物流信息写入聚水潭
- **异常检测** — 扫描超时 / 重量异常订单

### 🆔 身份证认证
- OCR 识别身份证图片
- 自动上传到聚水潭认证系统
- 支持双面识别 + 拆图

## 🔧 技术栈

| 组件 | 技术 |
|------|------|
| AI Agent | Python + FastAPI |
| 前端 | Vue.js（H5 SPA）+ 原生 JS（小助手）|
| ERP 集成 | Python + JST Open API |
| 容器 | Docker / Docker Compose |
| 物流追踪 | 快递100 API + 货易达 API |
| OCR | PaddleOCR / RapidOCR |
| 数据库 | SQLite + MySQL + MariaDB |

## 📸 截图

> AI 购物助手对话界面、订单推送流程、库存同步看板、身份证认证系统

## 🔑 环境变量

参考各目录下的 `.env.example` 或 `config.py` 文件。

## 📄 License

Private — USTAR GmbH
