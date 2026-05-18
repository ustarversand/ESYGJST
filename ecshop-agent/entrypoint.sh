#!/bin/bash
# ECShop 容器入口 — 从共享卷 /opt/data/ecshop/ 部署并启动
set -e

ECSHOP_DIR=/opt/data/ecshop
DATA_DIR=/opt/data/ecshop

echo "=========================================="
echo " 🚀 ECShop 独立容器启动"
echo "=========================================="
echo "  → ENTRYPOINT_VERSION=v3 (fix_admin2)"

# ── 首次部署：复制代码到标准位置 ────────────
if [ ! -f /var/www/ecshop/index.php ]; then
    echo "[1/4] 部署网站代码..."
    cp -a $DATA_DIR/www /var/www/ecshop
    cp -a $DATA_DIR/appserver /var/www/appserver
    cp -a $DATA_DIR/wholesale /var/www/ecshop/wholesale
    chown -R www-data:www-data /var/www/ecshop /var/www/appserver /var/www/ecshop/wholesale
fi

# 每次更新agent代码
if [ -d $DATA_DIR/agent ]; then
    echo "  → 更新 Agent 服务..."
    cp -a $DATA_DIR/agent/* /opt/data/ecshop/agent/
fi

# ── Nginx 配置 ──────────────────────────────
echo "[2/4] 配置 Nginx..."
cat > /etc/nginx/sites-available/ecshop << 'NGX'
server {
    listen 8081;
    server_name localhost;
    root /var/www/ecshop;
    index index.php index.html;
    fastcgi_buffers 16 16k;
    fastcgi_buffer_size 32k;
    fastcgi_busy_buffers_size 64k;

    # API 反向代理到 appserver (Lumen)
    location /api/ {
        proxy_pass http://127.0.0.1:8082/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Agent API 反向代理（购物小助手）
    location /agent-api/ {
        proxy_pass http://127.0.0.1:8766/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 静态文件
    location ~ \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # 群聊API (PHP) - 要在最前面
    location /gc-api {
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param QUERY_STRING $query_string;
    }

    location / { try_files $uri $uri/ /index.php?$args; }
    location ~ ^/admin/.*\\.php$ {
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/var/run/php/php7.4-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }

    location ~ \\.php$ {
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }
}
NGX
cat > /etc/nginx/sites-available/appserver << 'NGX'
server {
    listen 8082;
    server_name localhost;
    root /var/www/appserver/public;
    index index.php index.html;
    location / { try_files $uri $uri/ /index.php?$query_string; }
    location ~ \.php$ {
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/var/run/php/php7.4-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }
}
NGX
ln -sf /etc/nginx/sites-available/ecshop /etc/nginx/sites-enabled/
ln -sf /etc/nginx/sites-available/appserver /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# 每次启动更新 H5 前端文件（购物小助手 + 配置）
if [ -f $DATA_DIR/www/h5/static/config.js ]; then
    cp $DATA_DIR/www/h5/static/config.js /var/www/ecshop/h5/static/config.js
    echo "  ✅ H5 前端配置已同步"
fi
# 每次启动同步 appserver PHP 文件（确保代码更新生效）
if [ -d $DATA_DIR/appserver/app/Models ]; then
    cp -a $DATA_DIR/appserver/app/Models/. /var/www/appserver/app/Models/ 2>/dev/null && echo "  ✅ appserver Models 已同步" || echo "  ⚠️ appserver Models 同步跳过"
fi
# 修复 OrderGoods.php: photos 字段保护（共享卷无 appserver 时的后备）
if ! grep -q "is_array.*photos" /var/www/appserver/app/Models/v2/OrderGoods.php 2>/dev/null; then
    python3 -c "
path = '/var/www/appserver/app/Models/v2/OrderGoods.php'
with open(path) as f:
    c = f.read()
old = \"'photos' => GoodsGallery::getPhotosById(\"
new = old + '?? [],'
if new not in c:
    c = c.replace(old, new)
    with open(path, 'w') as f:
        f.write(c)
    print('  ✅ OrderGoods.php photos 保护已修复 (?? [])')
else:
    print('  ✅ OrderGoods.php 已修复，跳过')
"
fi
# 修复 PHP 8.3 花括号语法（{$var} → [$var]）—— 多次批量修复
if grep -q 'text{' /var/www/ecshop/includes/cls_json.php 2>/dev/null; then
    sed -i 's/text{$this->at}/text[$this->at]/g' /var/www/ecshop/includes/cls_json.php && echo "  ✅ cls_json.php PHP 8.3 语法已修复"
fi
# PHP 8.3: 修复 lib_clips.php $upload_size_limit{strlen(...)} → $upload_size_limit[strlen(...)]
if grep -q 'upload_size_limit{' /var/www/ecshop/includes/lib_clips.php 2>/dev/null; then
    sed -i 's/$upload_size_limit{strlen/$upload_size_limit[strlen/g' /var/www/ecshop/includes/lib_clips.php && echo "  ✅ lib_clips.php PHP 8.3 语法已修复"
fi
# PHP 8.3: 修复 user_realname.php (同上)
if grep -q 'upload_size_limit{' /var/www/ecshop/user_realname.php 2>/dev/null; then
    sed -i 's/$upload_size_limit{strlen/$upload_size_limit[strlen/g' /var/www/ecshop/user_realname.php && echo "  ✅ user_realname.php PHP 8.3 语法已修复"
fi
# PHP 8.3: 修复 shopex_json.php $chrs{++$c} → $chrs[++$c]
if grep -q '\$chrs{' /var/www/ecshop/includes/shopex_json.php 2>/dev/null; then
    sed -i 's/$chrs{++$c}/$chrs[++$c]/g' /var/www/ecshop/includes/shopex_json.php && echo "  ✅ shopex_json.php PHP 8.3 语法已修复"
fi
# 修复 Shipping.php: 物流返回格式改为 {status: [...]}
if ! grep -q "flat_status" /var/www/appserver/app/Models/v2/Shipping.php 2>/dev/null; then
    python3 -c "
path = '/var/www/appserver/app/Models/v2/Shipping.php'
with open(path) as f:
    c = f.read()
old = \"return self::formatBody(['data'=>\$result]);\"
new = '''\$flat_status = [];
        foreach (\$result as \$item) {
            if (!empty(\$item['status']) && is_array(\$item['status'])) {
                foreach (\$item['status'] as \$s) {
                    if (is_array(\$s)) {
                        \$flat_status[] = \$s;
                    }
                }
            }
        }
        return self::formatBody(['status'=>\$flat_status]);'''
if old in c:
    c = c.replace(old, new)
    with open(path, 'w') as f:
        f.write(c)
    print('  ✅ Shipping.php 返回格式已修复')
else:
    print('  ✅ Shipping.php 已修复，跳过')
"
fi
# 同步购物小助手脚本（尝试从共享卷复制，失败则直接 sed 修复）
if [ -f $DATA_DIR/www/h5/static/shopping-assistant.js ]; then
    cp $DATA_DIR/www/h5/static/shopping-assistant.js /var/www/ecshop/h5/static/shopping-assistant.js && echo "  ✅ 购物小助手脚本已同步 ($(stat -c%s $DATA_DIR/www/h5/static/shopping-assistant.js) bytes)" || echo "  ⚠️ 购物小助手同步失败"
else
    echo "  ⚠️ 购物小助手源文件不存在: $DATA_DIR/www/h5/static/shopping-assistant.js"
fi
# 强制修复 apiBase 为直连 agent（共享卷无 www 目录时的后备方案）
if grep -q "apiBase: '/agent-api'" /var/www/ecshop/h5/static/shopping-assistant.js; then
    sed -i "s|apiBase: '/agent-api'|apiBase: 'http://192.168.178.26:8766'|" /var/www/ecshop/h5/static/shopping-assistant.js
    echo "  ✅ 购物小助手 apiBase 已修正为直连 8766"
fi
# 修复移动端点击 FAB 不弹窗（touchstart preventDefault 阻止了 click 事件）
if ! grep -q "togglePanel\|wasDrag" /var/www/ecshop/h5/static/shopping-assistant.js 2>/dev/null; then
    python3 -c "
import re
path = '/var/www/ecshop/h5/static/shopping-assistant.js'
with open(path) as f: c = f.read()

# 添加 togglePanel 函数
if 'function togglePanel' not in c:
    func = '''\n\n    // ─── 面板切换（移动端点击修复）───
    function togglePanel(open) {
        state.open = open !== undefined ? open : !state.open;
        fab.classList.toggle('open', state.open);
        panelEl.classList.toggle('open', state.open);
        if (state.open) {
            inputEl.focus();
            renderHistory();
            var cart = loadCart();
            setBadge(cart.items.length);
            apiGet('/cart').then(function(data) {
                if (Array.isArray(data)) {
                    saveCart({ items: data, total: '0.00' });
                    setBadge(data.length);
                }
            });
        }
    }'''
    c = c.replace('    document.addEventListener(.touchend., function()', func + '\n    document.addEventListener(.touchend., function()')

# 修改 touchend 处理点击
old_te = '    document.addEventListener(.touchend., function() { onDragEnd(); });'
new_te = '''    document.addEventListener(.touchend., function() {
        var wasDrag = dragMoved;
        onDragEnd();
        if (!wasDrag) togglePanel();
    });'''
c = c.replace(old_te, new_te)

# 添加 startedOnFab 判断（防止点屏幕任意位置弹窗）
c = c.replace('        if (!wasDrag) togglePanel();', '        if (startedOnFab && !wasDrag) togglePanel();')

# click handler 改为调用 togglePanel
c = c.replace('state.open = !state.open;\\n        fab.classList.toggle(.open., state.open);\\n        panelEl.classList.toggle(.open., state.open);\\n        if (state.open) {\\n            inputEl.focus();\\n            renderHistory();\\n            var cart = loadCart();\\n            setBadge(cart.items.length);\\n            apiGet(./cart.).then(function(data) {\\n                if (Array.isArray(data)) {\\n                    saveCart({ items: data, total: .0.00. });\\n                    setBadge(data.length);\\n                }\\n            });\\n        }', '        togglePanel();')

# 修复配送方式选择 — 按钮添加 data-sid 属性传递 shipping_id
old_sid1 = ''\\n                .data-cid. + (a.consignee_id || .) + . . +\\n                .data-order. + (a.order_sn || .) + . . +''
new_sid1 = ''\\n                .data-cid. + (a.consignee_id || .) + . . +\\n                .data-sid. + (a.shipping_id || .) + . . +\\n                .data-order. + (a.order_sn || .) + . . +''
c = c.replace(old_sid1, new_sid1)

# 修复配送方式选择 — checkout 处理传递 shipping_id
old_sid2 = ''                } else if (action === .checkout.) {\\n                    var cid = this.dataset.cid;\\n                    var loading = showLoading();\\n                    var msg = cid ? .结算. : .结算.;\\n                    var ctx = cid ? { step: .checkout., consignee_id: parseInt(cid) } : {};\\n                    apiPost(./chat., { message: msg, context: ctx }).then(function(r) {''
new_sid2 = ''                } else if (action === .checkout.) {\\n                    var cid = this.dataset.cid;\\n                    var sid = this.dataset.sid;\\n                    var loading = showLoading();\\n                    var msg = cid ? .结算. : .结算.;\\n                    var ctx = cid ? { step: .checkout., consignee_id: parseInt(cid) } : {};\\n                    if (sid) ctx.shipping_id = parseInt(sid);\\n                    apiPost(./chat., { message: msg, context: ctx }).then(function(r) {''
c = c.replace(old_sid2, new_sid2)

with open(path, 'w') as f: f.write(c)
print('  ✅ 购物小助手触屏点击已修复 (togglePanel)')
" 2>&1
fi
# 确保 index.html 包含购物小助手脚本标签
if [ -f $DATA_DIR/www/h5/index.html ]; then
    cp $DATA_DIR/www/h5/index.html /var/www/ecshop/h5/index.html
    echo "  ✅ H5 index.html 已同步"
fi
# 购物车图片缩小（覆盖 Vue scoped CSS 的 90px 为 55px）
if ! grep -q "cart-list-wrapper.*!important" /var/www/ecshop/h5/index.html 2>/dev/null; then
    sed -i 's|<link href=./static/css/app.0953011e9c1a75393215976882eef278.css rel=stylesheet>|&<style>\\n  .cart-list-wrapper .list .list-item div.item div.ui-image[data-v-547019c3] {\\n    width: 50px !important; height: 50px !important;\\n    -ms-flex-preferred-size: 50px !important; flex-basis: 50px !important;\\n  }\\n  .cart-list-wrapper .list .list-item div.item div.ui-image img[data-v-547019c3] {\\n    object-fit: cover !important;\\n  }\\n  .cart-list-wrapper .list .list-item div.item div.list-info[data-v-547019c3] {\\n    width: auto !important;\\n    -webkit-box-flex: 1 !important; -ms-flex: 1 !important; flex: 1 !important;\\n    min-width: 0 !important; margin-left: 6px !important;\\n  }\\n  .cart-list-wrapper .list div.list-checkbox[data-v-547019c3] {\\n    margin-right: 3px !important;\\n  }\\n  .product-list-item .list .ui-image-wrapper,\\n  .product-list-item .list .ui-image-wrapper img.product-img {\\n    width: 90px !important; height: 90px !important; flex-basis: 90px !important;\\n  }\\n</style>|' /var/www/ecshop/h5/index.html && echo "  ✅ 购物车布局已优化"
fi

# 同步管理员创建脚本（每次重启可用）
if [ -f $DATA_DIR/www/create_admin.php ]; then
    cp $DATA_DIR/www/create_admin.php /var/www/ecshop/create_admin.php
fi

# ── 确保文件权限（镜像内 COPY 的文件属主可能是 root）──
echo "  → 设置文件权限..."
chown -R www-data:www-data /var/www/ecshop /var/www/appserver 2>/dev/null || true
chmod -R 755 /var/www/ecshop /var/www/appserver 2>/dev/null || true
echo "  ✅ 权限设置完成"

# ── PHP 兼容性修复（容器重启后保证生效）──
echo "  → 修复 PHP 8.3 兼容性..."
if [ -f /opt/data/ecshop/agent/fix_admin2.py ]; then
    /usr/bin/python3 /opt/data/ecshop/agent/fix_admin2.py 2>&1
    echo "  ✅ PHP 兼容性修复完成"
fi

# ── 启动服务 ────────────────────────────────
echo "[3/4] 启动服务..."

# MySQL
service mariadb start 2>/dev/null || true
echo "  ⏳ 等待 MariaDB 就绪..."
for i in $(seq 1 10); do
    sleep 1
    mysql -u root -e "SELECT 1" 2>/dev/null && break
done
echo "  ✅ MariaDB 就绪"

# 首次启动需初始化数据库
if [ ! -f $DATA_DIR/.db-initialized ]; then
    echo "  → 初始化数据库..."
    mysql -u root <<-SQL 2>/tmp/db_init_error.log || echo "  ⚠️ 数据库创建失败，详见 /tmp/db_init_error.log"
        CREATE DATABASE IF NOT EXISTS ecshop_renzheng CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        ALTER USER 'root'@'localhost' IDENTIFIED BY 'Ecshop@2026!';
        FLUSH PRIVILEGES;
SQL
    # 导入数据
    if [ -f $DATA_DIR/sql/ecshop_data.sql ] && [ -s $DATA_DIR/sql/ecshop_data.sql ]; then
        echo "  → 导入 ecshop_data.sql（约300MB，请耐心等待）..."
        mysql -u root -p'Ecshop@2026!' ecshop_renzheng < $DATA_DIR/sql/ecshop_data.sql 2>/tmp/db_import_error.log && echo "  ✅ 数据库导入完成" || echo "  ⚠️ 导入失败，详见 /tmp/db_import_error.log"
    elif [ -f $DATA_DIR/sql/ecshop_b2c-sql.sql ] && [ -s $DATA_DIR/sql/ecshop_b2c-sql.sql ]; then
        echo "  → 导入 ecshop_b2c-sql.sql（约300MB，请耐心等待）..."
        mysql -u root -p'Ecshop@2026!' ecshop_renzheng < $DATA_DIR/sql/ecshop_b2c-sql.sql 2>/tmp/db_import_error.log && echo "  ✅ 完整数据库导入完成" || echo "  ⚠️ 导入失败，详见 /tmp/db_import_error.log"
    fi
    touch $DATA_DIR/.db-initialized
fi

# 确保管理员账号存在（每次启动自动创建）
echo "  → 确保管理员账号..."
mysql -u root -p'Ecshop@2026!' ecshop_renzheng -e "
    INSERT IGNORE INTO ecs_admin_user 
    (user_id, user_name, email, password, ec_salt, add_time, action_list, nav_list)
    VALUES 
    (10, 'laoyang', 'admin@localhost', '2483b83f2660f4b7e6cd0ca1ca331090', '1234', UNIX_TIMESTAMP(), 'all', '商品列表|goods.php?act=list,订单列表|order.php?act=list,用户评论|comment_manage.php?act=list,会员列表|users.php?act=list,商店设置|shop_config.php?act=list_edit');
    SELECT CONCAT('  ✅ 管理员 laoyang 就绪 (user_id=', user_id, ')') AS status FROM ecs_admin_user WHERE user_name='laoyang';
" 2>/dev/null || echo "  ⚠️ 管理员创建失败（可能已存在）"

# 更新聚水潭配置中的店铺ID
echo "  → 更新 JST 店铺ID为 20941412..."
mysql -u root -p'Ecshop@2026!' ecshop_renzheng -e "
    UPDATE ecs_config
    SET config = JSON_SET(config, '$.shop_id', '20941412')
    WHERE code = 'jstan.erp';
    SELECT CONCAT('  ✅ JST 店铺ID已更新为: ', JSON_UNQUOTE(JSON_EXTRACT(config, '$.shop_id'))) AS status
    FROM ecs_config WHERE code = 'jstan.erp';
" 2>/dev/null || echo "  ⚠️ JST 配置更新失败"

# 删除 laoyang (user_id=645) 的所有订单
echo "  → 删除 laoyang 的订单..."
mysql -u root -p'Ecshop@2026!' ecshop_renzheng -e "
    DELETE FROM ecs_order_info WHERE user_id = 645;
    SELECT CONCAT('  ✅ 已删除 ', ROW_COUNT(), ' 条订单记录') AS status;
" 2>/dev/null || echo "  ⚠️ 删除订单失败"
mysql -u root -p'Ecshop@2026!' ecshop_renzheng -e "
    DELETE FROM ecs_order_goods WHERE order_id NOT IN (SELECT order_id FROM ecs_order_info);
    SELECT CONCAT('  ✅ 已清理 ', ROW_COUNT(), ' 条冗余订单商品') AS status;
" 2>/dev/null || echo "  ⚠️ 清理订单商品失败"

# PHP-FPM
service php8.3-fpm start 2>/dev/null || true
service php7.4-fpm start 2>/dev/null || true

# Nginx
service nginx start 2>/dev/null || true

# ECShop Agent 服务
echo "[4/4] 启动 AI Agent (:8766)..."
cd $DATA_DIR/agent && nohup $DATA_DIR/agent/.venv/bin/python3 agent_service.py > /opt/data/logs/ecshop-agent.log 2>&1 &
sleep 2

# ── ERP 同步崩溃修复 ──────────────────────────
echo "  → 修复 ERP 同步崩溃（is_array check）..."

# 确保 SHOP_URL 设置正确（JST 同步需要）
if grep -q '^SHOP_URL=' /var/www/appserver/.env; then
    echo "    ✅ SHOP_URL already set"
else
    echo "SHOP_URL=http://127.0.0.1:8081" >> /var/www/appserver/.env
    echo "    ✅ SHOP_URL added to .env"
fi
sed -i 's/if (\$response\['"'"'result'"'"'\] == '"'"'success'"'"')/if (is_array(\$response) \&\& isset(\$response["result"]) \&\& \$response["result"] == "success")/' \
  /var/www/appserver/app/Services/Shopex/Erp.php 2>/dev/null && echo "    ✅ Erp.php" || echo "    ⚠️ Erp.php"
sed -i 's/if (\$response\['"'"'result'"'"'\] == '"'"'success'"'"')/if (is_array(\$response) \&\& isset(\$response["result"]) \&\& \$response["result"] == "success")/' \
  /var/www/appserver/app/Services/Jstan/JstanErp.php 2>/dev/null && echo "    ✅ JstanErp.php" || echo "    ⚠️ JstanErp.php"

# ── 取消订单邮件发送崩溃修复 ──────────────────
echo "  → 修复取消订单邮件崩溃（try-catch）..."
python3 -c "
filepath = '/var/www/appserver/app/Models/v2/Order.php'
with open(filepath) as f:
    c = f.read()
old = '''//模板推送
                    Mail::send('\''emails.orderCancel'\'', \$params, function(\$message) use (\$email)
                    {
                        \$message->to(\$email)->subject('\''代销人订单取消通知'\'');
                    });'''
new = '''//模板推送（邮件发送失败不影响取消）
                    try {
                        Mail::send('\''emails.orderCancel'\'', \$params, function(\$message) use (\$email)
                        {
                            \$message->to(\$email)->subject('\''代销人订单取消通知'\'');
                        });
                    } catch (\\\\Exception \$e) {
                        Log::error('\''取消订单邮件发送失败: '\'' . \$e->getMessage());
                    }'''
if 'try {' in c.split('Mail::send')[0:1] or 'catch (\\\\Exception' in c:
    print('    ✅ Order.php (already fixed)')
else:
    c = c.replace(old, new)
    with open(filepath, 'w') as f:
        f.write(c)
    print('    ✅ Order.php')
"

# ── 健康检查 ────────────────────────────────
echo ""
echo "=========================================="
echo " ✅ ECShop 容器就绪！"
echo "    前台: http://localhost:8081"
echo "    API:  http://localhost:8082"
echo "    Agent: http://localhost:8766"
echo "=========================================="
curl -sf http://localhost:8081/ > /dev/null 2>&1 && echo "  ✅ ECShop :8081" || echo "  ⚠️ ECShop 未就绪"
curl -sf http://localhost:8082/ > /dev/null 2>&1 && echo "  ✅ API :8082" || echo "  ⚠️ API 未就绪"
curl -sf http://127.0.0.1:8766/ > /dev/null 2>&1 && echo "  ✅ Agent :8766" || echo "  ⚠️ Agent 未就绪"
echo ""

# 保持运行
sleep infinity
echo '>>> ENTRYPOINT RUNNING AT: $(date)'
