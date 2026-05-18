# 🛠️ 开发环境搭建

## 一、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                   分拣系统网络                                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐     192.168.1.100 (网关/NUC)              │
│  │   NUC/服务器  │ ◄─────────► Docker                    │
│  │  (控制中台)  │              (FastAPI+Redis+Mongo)        │
│  └──────┬───────┘                                         │
│         │                                                  │
│    ┌────┼────┬────┐                                      │
│    │    │    │    │                                      │
│  ┌─┴─┐ ┌┴─┐ ┌┴─┐                                     │
│  │   │ │   │ │   │                                     │
│  ▼   ▼ ▼   ▼ ▼   ▼                                     │
│ Piper DC1 Jetson WiFi相机                               │
│ 192.168.1.50  192.168.1.51                                │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、安装步骤

### 1. 基础软件 (NUC/服务器)

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# 安装Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 安装Node.js
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# 安装Python
sudo apt install -y python3.10 python3-pip python3-venv
```

### 2. 控制中台服务

```bash
# 创建项目目录
mkdir -p ~/sorting-system
cd ~/sorting-system

# 创建docker-compose.yml
cat > docker-compose.yml << 'YML'
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  mongodb:
    image: mongo:6
    ports:
      - "27017:27017"
    volumes:
      - mongo_data:/data
    environment:
      MONGO_INITDB_ROOT_USERNAME: admin
      MONGO_INITDB_ROOT_PASSWORD: sorting123

  control-api:
    image: python:3.10-slim
    ports:
      - "8000:8000"
    volumes:
      - ./app:/app
    working_dir: /app
    command: pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port 8000
    depends_on:
      - redis
      - mongodb

volumes:
  redis_data:
  mongo_data:
YML
```

### 3. 边缘计算 (Jetson Orin)

```bash
# 安装JetPack 6.0
# 下载: https://developer.nvidia.com/jetpack

# 安装DeepStream
sudo apt install -y deepstream-7.0

# 安装PyTorch TensorRT
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 部署YOLO模型
cd /opt/nvidia/deepstream/triton-sav/
wget https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.pt
```

### 4. Piper 机械臂

```bash
# 安装Python SDK
pip install pypiper

# 测试连接
python3 -c "import pypiper; print('OK')"

# 配置网络
# 默认IP: 192.168.1.50
# 修改: sudo vi /etc/network/interfaces
```

### 5. DABAI DC1

```bash
# 安装SDK (参考官方文档)
# 默认IP: 192.168.1.51

# 测试API
curl http://192.168.1.51:8080/status
```

---

## 三、网络配置

### 路由器设置

| 设备 | IP | 端口 |
|------|-----|------|
| NUC | 192.168.1.100 | 8000, 27017, 6379 |
| Piper | 192.168.1.50 | 8080 |
| DC1 | 192.168.1.51 | 8080 |
| Jetson | 192.168.1.52 | - |

### 防火墙

```bash
# 开放端口
sudo ufw allow 8000/tcp
sudo ufw allow 27017/tcp
sudo ufw allow 6379/tcp
```

---

## 四、验证测试

```bash
# 1. Docker服务
docker ps
# 应该看到 redis, mongodb 运行中

# 2. API服务
curl http://localhost:8000/health
# {"status": "ok"}

# 3. Piper连接
python3 -c "from pypiper import Piper; p = Piper(); p.get_status()"

# 4. DC1相机
curl http://192.168.1.51:8080/status
```

---

## 五、启动命令

```bash
cd ~/sorting-system

# 启动所有服务
docker-compose up -d

# 启动控制中台
cd app
python3 main.py

# 查看日志
docker-compose logs -f
```
