FROM python:3.13-slim

LABEL name="直邮管家 ZYGJ" \
      description="德国直邮代发推单系统" \
      version="2.0"

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 curl libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app.py config.py auth.py price_match.py ./
COPY push_engine.py push_records.py excel_parser.py ./
COPY order_parser/ order_parser/
COPY heuste_client.py heuste_sdk.py idcard_handler.py models.py ./
COPY query_jst_products.py ./
COPY data/ data/
COPY templates/ templates/
COPY 身份证上传/ 身份证上传/
COPY scripts/ scripts/
COPY static/ static/

# 环境变量（运行时通过 -e 覆盖）
ENV JST_APP_KEY=""
ENV JST_APP_SECRET=""
ENV JST_TOKEN=""
ENV ZYGJ_PORT=8899
ENV ZYGJ_DEBUG=false

EXPOSE 8899

# 使用 gunicorn 启动
CMD ["sh", "-c", "gunicorn -w 2 -b 0.0.0.0:${ZYGJ_PORT:-8899} app:app"]
