#!/usr/bin/env python3
"""Fix nginx config: add /agent-api/ proxy -> 127.0.0.1:8766"""
import re, os

config_path = "/etc/nginx/sites-enabled/ecshop"
if not os.path.exists(config_path):
    print(f"{config_path} not found")
    exit(1)

with open(config_path) as f:
    content = f.read()

if "agent-api" in content:
    print("agent-api proxy already configured")
else:
    proxy_block = '''
    # Agent API proxy -> FastAPI on 8766
    location /agent-api/ {
        proxy_pass http://127.0.0.1:8766/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }'''
    last_brace = content.rstrip().rfind("}")
    content = content[:last_brace] + proxy_block + "\n" + content[last_brace:]
    with open(config_path, "w") as f:
        f.write(content)
    print("agent-api proxy block added to nginx config")
