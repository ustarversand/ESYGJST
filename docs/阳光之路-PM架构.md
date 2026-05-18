# 阳光之路 - ECShop 聚水潭对接项目 PM 架构文档

**项目名称**: 阳光之路  
**版本**: v1.0.0  
**创建日期**: 2026-05-16  
**状态**: 待确认实施  
**类型**: PM 架构设计文档

---

## 1. 项目概述

### 1.1 背景

ECShop 商城订单需要同步到聚水潭 ERP 系统。当前问题：

- **API 返回成功但后台不显示**：orders.upload 返回 code=0 "保存成功"，但聚水潭后台看不到订单
- **验证接口失效**：orders.query、orders.single.query 已转奇门（阿里巴巴 ERP），无法确认订单是否真正入库
- **店铺授权问题**：部分店铺 ID（20941412）不在 API 授权列表中

### 1.2 目标

建立可靠的订单同步机制，确保：
1. 订单推送状态可追踪
2. 推送失败可自动重试
3. 后台可视化确认收到

---

## 2. 方案设计

### 2.1 方案名称：混合方案（本地记录 + 定时重试 + 后台可视化）

**推荐理由**：最完善的解决方案，结合本地追踪+自动化重试+人工确认

### 2.2 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        阳光之路系统架构                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐    │
│  │  ECShop 商城  │────▶│  阳光之路    │────▶│  聚水潭 ERP  │    │
│  │  订单系统    │     │  同步引擎    │     │  订单上传   │    │
│  └──────────────┘     └──────────────┘     └──────────────┘    │
│         │                    │                    │              │
│         │                    ▼                    ▼              │
│         │            ┌──────────────┐     ┌──────────────┐    │
│         │            │  本地订单库   │     │  JST 后台   │    │
│         │            │  (MySQL)      │     │  确认收到   │    │
│         │            └──────────────┘     └──────────────┘    │
│         │                    │                                 │
│         │                    ▼                                 │
│         │            ┌──────────────┐                          │
│         │            │  后台管理界面 │                          │
│         │            │  (可视化)    │                          │
│         └───────────▶└──────────────┘                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 核心组件

| 组件 | 技术选型 | 功能 |
|------|----------|------|
| 同步引擎 | Python 3 | 订单读取、格式转换、API 推送 |
| 本地订单库 | MySQL | 记录推送状��、重试次数 |
| 后台管理界面 | PHP/Web | 可视化确认、状态查看 |
| 定时任务 | cron | 自动重试失败订单 |

---

## 3. 数据模型

### 3.1 本地订单库表

```sql
CREATE TABLE `jst_sync_orders` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `ecshop_order_id` VARCHAR(32) NOT NULL COMMENT 'ECShop订单号',
  `jst_order_id` VARCHAR(64) COMMENT '聚水潭订单号',
  `shop_id` VARCHAR(16) NOT NULL COMMENT '店铺ID',
  `order_data` JSON NOT NULL COMMENT '订单完整数据',
  
  -- 推送状态
  `push_status` ENUM('pending','success','failed','confirmed') DEFAULT 'pending',
  `push_times` INT DEFAULT 0 COMMENT '推送次数',
  `last_push_time` DATETIME COMMENT '最后推送时间',
  `push_error` TEXT COMMENT '错误信息',
  
  -- JST回调状态
  `jst_status` VARCHAR(16) COMMENT '聚水潭订单状态',
  `jst_confirm_time` DATETIME COMMENT 'JST确认时间',
  
  -- 审计
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  
  UNIQUE KEY `idx_ecshop_order_id` (`ecshop_order_id`),
  KEY `idx_push_status` (`push_status`),
  KEY `idx_created_at` (`created_at`)
);
```

### 3.2 状态流转

```
pending → success → confirmed
    ↓       ↓
   failed ──┘
              (手动确认/自动回调)
```

| 状态 | 说明 | 后续动作 |
|------|------|----------|
| pending | 待推送 | 同步引擎处理 |
| success | 推送成功 | 等待 JST 回调确认 |
| failed | 推送失败 | 自动重试/人工处理 |
| confirmed | JST已确认 | 流程完成 |

---

## 4. 功能模块

### 4.1 同步引擎

```python
# 核心流程
class SyncEngine:
    def run(self):
        # 1. 读取待同步订单
        orders = self.fetch_pending_orders()
        
        for order in orders:
            # 2. 推送前：记录到本地库
            self.save_to_local(order)
            
            # 3. 调用API推送
            result = self.push_to_jst(order)
            
            # 4. 更新状态
            if result.success:
                self.update_status(order, 'success')
            else:
                self.update_status(order, 'failed', result.error)
                self.schedule_retry(order)
```

### 4.2 定时重试

```python
# 自动重试逻辑
class RetryScheduler:
    RETRY_INTERVALS = [60, 300, 900, 3600]  # 1m, 5m, 15m, 1h
    MAX_RETRIES = 4
    
    def schedule_retry(self, order, attempt):
        if attempt >= self.MAX_RETRIES:
            self.notify_admin(order)  # 人工介入
            return
        
        delay = self.RETRY_INTERVALS[attempt]
        self.set_timer(order.id, delay, self.retry_push)
```

### 4.3 后台管理界面

```
├── 订单列表
│   ├── 待推送 (pending)
│   ├── 推送成功 (success)
│   ├── 推送失败 (failed)
│   └── 已确认 (confirmed)
│
├── 订单详情
│   ├── ECShop 信息
│   ├── 推送日志
│   └── 手动操作
│
└── 统计面板
    ├── 今日推送数
    ├── 成功率
    └── 失败原因分布
```

---

## 5. 商品编码映射

### 5.1 映射表

| ECShop 商品名称 | 聚水潭 SKU | 价格 |
|---------------|------------|------|
| 德爱白金pre | 4056631003435BJP | 195 |
| 德爱白金1段 | 4056631003459BJ1 | 195 |
| 德爱白金2段 | 4056631003473BJ2 | 195 |
| 至尊1+ | 7613287296085ZZ1+ | 145 |
| 乐活 | 0705044LHTK | - |
| 叶黄素 | 0712020YHS | - |
| 马膏 | 0715030MG | - |

### 5.2 映射逻辑

```python
def map_sku(product_name):
    """商品名称 → SKU"""
    return PRODUCT_SKU_MAP.get(product_name, None)

def map_price(product_name):
    """商品名称 → 价格"""
    return MILK_POWDER_SKU.get(product_name, {}).get('price', None)
```

---

## 6. API 对接

### 6.1 当前可用 API

| 接口 | 方法 | 状态 |
|------|------|------|
| 订单推送 | orders.upload | ✅ 可用 |
| 订单查询 | orders.query | ❌ 已转奇门 |
| 订单验证 | orders.single.query | ❌ 已转奇门 |

### 6.2 API 配置

```python
API_URL = "https://open.erp321.com/api/open/query.aspx"
METHOD = "orders.upload"
APP_KEY = "d561deb348274f1ba3505ec4578870fd"
TOKEN = "cfda23ff97664494bc6fc5ab46f8ea48"
```

---

## 7. 实施计划

### 7.1 开发阶段

| 阶段 | 任务 | 预估工作量 |
|------|------|-----------|
| 1 | 数据库表设计 | 1h |
| 2 | 同步引擎核心 | 4h |
| 3 | 定时重试机制 | 2h |
| 4 | 后台管理界面 | 4h |
| 5 | 测试与调试 | 2h |

### 7.2 优先级

1. **P0**: 同步引擎核心（订单读取 + API 推送）
2. **P0**: 本地订单库记录
3. **P1**: 定时重试机制
4. **P2**: 后台管理界面
5. **P2**: 统计面板

---

## 8. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| API 返回成功但后台不显示 | 无法确认订单是否入库 | 依赖本地订单库追踪 |
| 店铺不在授权列表 | 推送失败 | 手动联系聚水潭添加 |
| 网络超时 | 推送失败 | 定时重试机制 |
| 商品SKU未映射 | 推送失败 | 映射表配置化 |

---

## 9. 成功标准

| 指标 | 目标 |
|------|------|
| 推送成功率 | ≥ 95% |
| 平均延迟 | ≤ 5分钟 |
| 可追溯率 | 100% |

---

## 10. 后续扩展

- [ ] 对接聚水潭回调接口（需聚水潭技术支持）
- [ ] 支持多店铺切换
- [ ] 订单状态双向同步
- [ ] 财务报表导出

---

## 附录：参考文件

- 同步脚本: `/opt/data/scripts/ecshop_jstan_sync.py`
- 工作流: `/opt/data/workspace/ustar-deploy/app/ustar_jst/workflows/ecshop_jst_sync.py`
- PHP封装: `/opt/data/ecshop/www/includes/lib_jstan.php`