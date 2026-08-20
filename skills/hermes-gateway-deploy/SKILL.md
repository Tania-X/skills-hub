---
name: hermes-gateway-deploy
description: "在远程服务器（阿里云 ECS 等 Linux）部署 Hermes Agent gateway 并暴露 webhook 端点，使外部系统（GitLab MR 事件 / devops 平台 / GitHub）通过 POST 触发 Hermes 加载 skill 执行。含 systemd 常驻、caddy 反代、双重认证（basic_auth + HMAC 验签）、验证与排障。当用户要求『把 webhook 部署到云端/服务器』『外部系统触发 Hermes 跑 skill』时使用。"
version: 1.0.0
author: Hermes Agent + Tania-X
license: MIT
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [hermes, webhook, gateway, deployment, systemd, caddy, aliyun]
    related_skills: [pr-ai-review-loop, github-auth]
---

# Hermes Webhook Gateway 云端部署

## 触发条件

- 需要让外部系统（GitLab / GitHub / devops 平台）通过 REST webhook 触发 Hermes 执行 skill
- 用户说「把 webhook 部署到云端」「服务器上跑 Hermes」等

## 关键认知（最容易踩的坑）

1. **webhook 是 gateway 平台的 adapter**：必须 `hermes gateway run` 启动，**不是 `hermes serve`**（serve 是桌面/JSON-RPC 后端，不含 webhook 路由）
2. 启用 webhook 需要两件事：`platforms.webhook.enabled=true`（config 或 .env `WEBHOOK_ENABLED=true`）+ **安装 `aiohttp`**——否则日志报 `No adapter available for webhook`
3. 订阅信息存于 `$HERMES_HOME/webhook_subscriptions.json`；路由 URL = `http://<host>:<port>/webhooks/<name>`
4. **--skills 指定的 skill 必须存在于该 HERMES_HOME/skills**，否则 agent 空跑、日志报 `Skill 'xxx' not found`
5. **mcp 包版本必须 ==1.26.x（Hermes 0.19 兼容版）**：Hermes 的 `tools/mcp_tool.py` 用旧 API 名 `from mcp.client.streamable_http import streamablehttp_client`，而 **mcp 2.0 改名为 `streamable_http_client`** → import 失败 → HTTP transport 被静默禁用，`hermes mcp test` 报 `requires HTTP transport but mcp.client.streamable_http is not available`。解法：`pip install 'mcp==1.26.0'` + 重启 gateway。**升级 mcp 包前先确认 Hermes 版本兼容**（mcp 2.x 只适用于支持新 API 的 Hermes 新版）。

## 部署步骤（Ubuntu / Debian）

```bash
# 1. 装 Hermes（PEP 668 限制：先装 python3.12-venv，再建 venv，不用 --break-system-packages）
sudo apt-get install -y python3.12-venv
mkdir -p /opt/hermes && cd /opt/hermes
python3 -m venv venv
./venv/bin/pip install hermes-agent -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. HERMES_HOME + .env（key 走 .env，不写明文进 config.yaml）
export HERMES_HOME=/opt/hermes/hermes-home
# .env 里放 DEEPSEEK_API_KEY=sk-... 等

# 3. 配置 provider + 启用 webhook 平台
./venv/bin/hermes config set model.provider deepseek
./venv/bin/hermes config set model.name deepseek-v4-flash
./venv/bin/hermes config set providers.deepseek.base_url https://api.deepseek.com
./venv/bin/hermes config set platforms.webhook.enabled true
./venv/bin/hermes config set platforms.webhook.extra.port 8644
./venv/bin/hermes config set platforms.webhook.extra.secret 'wh-global-secret-xxx'

# 4. 装 aiohttp（webhook adapter 依赖）
./venv/bin/pip install aiohttp

# 5. 注册订阅（--skills 指定触发时自动加载的 skill，--deliver log 便于排障）
./venv/bin/hermes webhook subscribe pr-review-loop \
  --prompt '对仓库 {repo} 分支 {ref} 执行 PR review loop。' \
  --skills pr-ai-review-loop --secret 'wh-route-secret-xxx' --deliver log

# 6. 把 skill 装进服务器 HERMES_HOME/skills（git clone skills-hub 或调 MCP install_skill）
mkdir -p $HERMES_HOME/skills && cp -r /tmp/skills-hub/skills/* $HERMES_HOME/skills/
# 验证：./venv/bin/hermes skills list

# 7. systemd 常驻
# Unit: Environment=HERMES_HOME=... / ExecStart=<venv>/bin/hermes gateway run / Restart=on-failure
```

## caddy 反代（复用已有网关）

- **容器内反代宿主机服务必须用 `host.docker.internal:<port>`**——`127.0.0.1` 指向 caddy 容器自己 → 502（skills-hub 8910 和本 gateway 都踩过）
- 容器启动需 `--add-host host.docker.internal:host-gateway`
- basic_auth 用独立凭据（`htpasswd -nbB <user> '<pass>'` 生成，注意 bash 会展开 `$`——hash 含 `$` 时必须写文件再让 python/sed 处理，不能直接内联进命令行）
- **复用已放行的端口**（如 4318）可避免开新安全组；改 Caddyfile 后 `docker restart caddy`（admin off 时 reload 不可用）

## 双重认证（推荐，实测有效）

1. **第一层**：caddy basic_auth（拦无凭据请求 → 401）
2. **第二层**：Hermes HMAC——header `X-Hub-Signature-256: sha256=<hmac-sha256(secret, body)>`（body 必须与签名时逐字节一致）

验证序列（本地 curl）：
```
no-auth                        → 401（caddy 拦）
with-basic-auth, no signature  → 401 Invalid signature（过 caddy，被 HMAC 拦）
with-basic-auth + valid sig    → {"status":"accepted","delivery_id":...}
```

## 排障速查

| 现象 | 原因 / 解法 |
|---|---|
| `No adapter available for webhook` | aiohttp 未装 |
| caddy 反代 502 | 目标写成 `127.0.0.1`（容器内）→ 改 `host.docker.internal` |
| 日志 `Skill 'xxx' not found` | skill 不在该 HERMES_HOME/skills → clone/install 后 `hermes skills list` 确认 |
| `Invalid signature` | secret 或 body 不匹配（body 要逐字节一致） |
| 重启 gateway 杀 agent / prune stale session | drain timeout 正常现象，agent 长任务会被中断 |
| `check_web_api_key returned False` | 依赖 web API key 的工具不可用，不影响 webhook 主流程 |
| `mcp test` 报 `streamable_http is not available` | **mcp 包被升到 2.x**（API 改名）→ `pip install 'mcp==1.26.0'` + 重启 gateway |

## 安全注意

- gateway 默认监听 **0.0.0.0:8644**（全接口）——建议**安全组不放行 8644**，只放行 caddy 入口端口
- 服务器 security_audit 会警告 SSH 密码认证开启（brute-force 风险），正式环境建议改 key 认证
- HMAC secret 与 basic_auth 凭据都是唯一防线，别写进公开仓库/文档

## 参考

- 本机桌面版可查 CLI 用法：`hermes webhook subscribe --help` / `hermes gateway --help`
- 实例凭据与拓扑：见本地 `WorkBuddy/.../cloud-services.md`（含真实 IP/凭据，**勿提交公开仓库**）
- 一次完整部署实录（全部命令实测）：`references/aliyun-deploy-2026-08-20.md`（已脱敏，`<SERVER_IP>` / `<USER>` 为占位符）
