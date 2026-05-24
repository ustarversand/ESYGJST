# 直邮管家 ZYGJ — 德国直邮推单系统

## 功能
- **手动推单**：填写收件人信息 + 商品 → 推入聚水潭
- **Excel批量推单**：上传Excel（支持35+种表头别名），自动解析+路由店铺+SKU匹配
- **一段话智能解析**：自然语言 → 结构化订单（"两罐爱他美白金pre 1375... 张梦露 浙江省..."）
- **身份证OCR识别**：上传照片自动识别姓名+身份证号（RapidOCR）
- **身份证认证上传**：对接 ccs.ustarvs.com 认证系统
- **物流查询**：对接货易达主站 API + 轨迹系统 track.heute-express.com
- **奶粉拆单**：每2罐自动拆一单
- **多店铺支持**：15个店铺，按关键词智能路由
- **数据隔离**：qiaoma 用户仅看乔妈店铺

## 快速启动

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 JST_APP_KEY / JST_APP_SECRET / JST_TOKEN

# 2. Docker 方式
bash build-and-run.sh

# 3. 或原生方式
source .env && python3 app.py
```

## 项目结构

```
zhiyouguanjia/
├── app.py                  # Flask Web (17 API routes)
├── config.py               # 配置（店铺/用户/JST）
├── push_engine.py          # 推单引擎（JST API + SKU匹配 + 身份证校验 + 奶粉拆单）
├── order_parser/           # 一段话解析器
│   ├── __init__.py         #   parse_order_text() 主入口
│   ├── fields.py           #   字段解析（数量/手机/地址/姓名）
│   └── product_utils.py    #   产品名扫描/匹配工具
├── excel_parser.py         # Excel解析器
├── idcard_handler.py       # 身份证OCR + 上传认证
├── auth.py                 # 登录认证
├── push_records.py         # 推单记录（JSON持久化）
├── heuste_client.py        # 货易达物流查询
├── heuste_sdk.py           # 货易达主站API SDK
├── 身份证上传/              # 身份证缓存模块
├── templates/              # 前端页面
├── Dockerfile              # 容器构建
└── docker-compose.yml      # 容器编排
```

> 数据（数据库、Token缓存、推单记录）通过 `.gitignore` 排除，不会提交。
