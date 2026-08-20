# 部署实录（2026-08-20，阿里云 ECS，已验证可复现）

> 本文件记录一次完整成功的部署细节，供复现/排障参照。所有命令均已实测。
> **脱敏说明**：`<SERVER_IP>` / `<USER>` 为占位符，真实值见本地 `cloud-services.md`（勿提交公开仓库）。

## 环境

- 阿里云 ECS `<SERVER_IP>`，Ubuntu 24.04，用户 `<USER>`（免密 sudo + docker 组）
- SSH 自动化用 paramiko（Windows 本地无 sshpass；`&` 调用操作符会被 Hermes 终端误判为后台符号，用 Start-Process 或 .ps1 文件规避）
- 服务器 pip 受 PEP 668 限制：先 `sudo apt-get install -y python3.12-venv` 再建 venv

## 安装（实测通过）

```bash
sudo mkdir -p /opt/hermes && sudo chown -R <USER>:<USER> /opt/hermes
cd /opt/hermes && python3 -m venv venv
./venv/bin/pip install hermes-agent -i https://pypi.tuna.tsinghua.edu.cn/simple
# 版本与本地桌面版一致：Hermes Agent v0.19.0 (2026.7.20)
```

## 配置（实测通过）

```bash
export HERMES_HOME=/opt/hermes/hermes-home
# .env 内容：DEEPSEEK_API_KEY=sk-... + HERMES_HOME=...（key 不写明文进 config.yaml）

./venv/bin/hermes config set model.provider deepseek
./venv/bin/hermes config set model.name deepseek-v4-flash
./venv/bin/hermes config set providers.deepseek.base_url https://api.deepseek.com
./venv/bin/hermes config set platforms.webhook.enabled true
./venv/bin/hermes config set platforms.webhook.extra.port 8644
./venv/bin/hermes config set platforms.webhook.extra.secret '<GLOBAL_SECRET>'
./venv/bin/pip install aiohttp   # 关键：缺它会 "No adapter available for webhook"
```

## 订阅（实测通过）

```bash
./venv/bin/hermes webhook subscribe pr-review-loop \
  --prompt '对仓库 {repo} 分支 {ref} 执行 PR review loop（opened/synchronize/reopened 事件）。' \
  --skills pr-ai-review-loop --secret '<ROUTE_SECRET>' --deliver log
# 输出：URL http://localhost:8644/webhooks/pr-review-loop，Secret 已设
```

## skill 安装（关键坑）

订阅的 `--skills pr-ai-review-loop` 要求该 skill 存在于**服务器**的 `$HERMES_HOME/skills/`。
漏装时 gateway 日志报 `Skill 'pr-ai-review-loop' not found`，agent 空跑。

```bash
cd /tmp && git clone --depth 1 https://github.com/Tania-X/skills-hub.git
mkdir -p $HERMES_HOME/skills && cp -r /tmp/skills-hub/skills/* $HERMES_HOME/skills/
export HERMES_HOME=/opt/hermes/hermes-home && ./venv/bin/hermes skills list  # 确认 3 个 enabled
```

## systemd（实测通过）

```
[Unit] Description=Hermes Agent Gateway (webhook for pr-review-loop) After=network.target
[Service] Type=simple User=<USER> Environment=HERMES_HOME=/opt/hermes/hermes-home
ExecStart=/opt/hermes/venv/bin/hermes gateway run Restart=on-failure RestartSec=5
[Install] WantedBy=multi-user.target
```

## caddy 复用 4318（实测通过）

- 原 `:4318` 反代 jaeger（OTLP 上报，探明**零流量**可复用）→ 改为 Hermes webhook
- 反代目标必须是 `host.docker.internal:8644`（容器内 127.0.0.1 = 容器自己 → 502）
- 容器已带 `--add-host host.docker.internal:host-gateway`
- 凭据：`htpasswd -nbB hermesuser '<pass>'`（hash 含 `$`，写文件后用 python 替换，避免 bash 展开）
- 改完 `docker restart caddy`（admin off，reload 不可用）

## 验证序列（实测结果）

```
no-auth                        → 401（caddy basic_auth）
+basic-auth, 无签名            → 401 {"error":"Invalid signature"}（HMAC 第二层）
+basic-auth + 正确签名         → {"status":"accepted","route":"pr-review-loop","delivery_id":"..."}
```

agent 激活证据（agent.log）：
```
[webhook] POST event=unknown route=pr-review-loop delivery=...
inbound message: platform=webhook ... msg='[IMPORTANT: The user has invoked the "pr-ai-review-loop" skill...'
agent.turn_context: session=... platform=webhook
API call #1: provider=deepseek ... latency=5.4s   ← LLM 正常
```

## 对外调用方式（给调用方）

```
POST http://<SERVER_IP>:4318/webhooks/pr-review-loop
Headers:
  Authorization: Basic <base64(hermesuser:pass)>
  X-Hub-Signature-256: sha256=<hmac-sha256("<ROUTE_SECRET>", body)>
  Content-Type: application/json
Body: {"repo": "...", "ref": "feat/xxx", "event": "opened|synchronize|reopened"}
```

## 待办（部署后遗留）

- webhook 调用方（GitLab MR 事件 / devops 平台）尚未接入 —— 服务端已就绪
- 服务器 security_audit 警告 SSH 密码认证开启，建议改 key 认证
- gateway 监听 0.0.0.0:8644，建议安全组不放行 8644（只留 caddy 4318 入口）
