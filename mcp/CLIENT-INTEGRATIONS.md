# MCP 客户端接入手册（CLIENT INTEGRATIONS）

> 能力中心 MCP 服务器的各客户端接入方式、参数与踩坑。
> **凭据约定**：所有用户名/密码/认证头不在本文件出现——按你本地 `cloud-services.md`（勿提交仓库）里的凭据填。

## 0. 服务信息（占位，替换为你的实际值）

| 项 | 值 |
|---|---|
| MCP 端点 | `http://<YOUR_SERVER_IP>:<YOUR_PORT>/mcp`（streamable-http） |
| 认证 | HTTP Basic（用户名/密码见本地 cloud-services.md；`Authorization: Basic <base64(user:pass)>`） |
| 工具 | `list_skills` / `get_skill` / `install_skill` / `refresh_cache` |

## 1. 接入矩阵

| 客户端 | 接入方式 | 服务标识 | 认证 | 备注 |
|---|---|---|---|---|
| **Hermes** | config.yaml `mcp_servers.skills_hub`（url + headers） | 无（config 内 key） | Basic header | Hermes 0.19 需 `mcp==1.26.x`（见 mcp/README） |
| **Claude Code** | `claude mcp add skills-hub --env SKILLS_HUB_INSTALL_DIR=~/.claude/skills -- python <path>/mcp_server.py`（stdio）或远程 URL | 任意唯一名 | 远程走 Basic header | 见 `../claude/README.md` |
| **Coze** | 工作流里接入 MCP（streamable-http），节点调 `get_skill` 拉 SKILL.md 当审查规则 | 任意唯一名 | 自定义 headers（Basic） | 无此坑；规则实时从 skill-hub 拉取 |
| **Dify** | 工具 → MCP（streamable-http） | **必须是 UUID**（见 §2 坑） | headers（Basic） | **1.17.0 有坑**，见 §2 |

## 2. Dify 接入（版本锚定 ⚠️）

> **先确认 Dify 版本**：以下坑位基于 **Dify 1.17.0**（docker，console 端口 8080，容器 `dify-api` / `dify-web` / `dify-plugin-daemon`）。
> **若版本更新，先试 UI 手动创建**——这两个坑可能已被修复。

### 2.1 坑 1：前端标识校验与后端 UUID 查询互斥（UI 手动创建不可行）

- 前端 `web/app/components/tools/mcp/hooks/use-mcp-modal-form.ts` 的校验：
  `isValidServerID = /^[a-z0-9_-]{1,24}$/`（小写字母/数字/下划线/连字符，≤24 字符）
- 后端 GET `/console/api/workspaces/current/tool-provider/mcp/tools/<id>` 按 **uuid 类型主键列**查询
  （`tool_mcp_providers.id`）——任何满足前端的短字符串会触发
  `invalid input syntax for type uuid` → 500；UUID（36 字符）又被前端正则拦截。
- **结论**：没有任何字符串能同时满足两者，1.17 的 UI 创建路径是坏的。

### 2.2 坑 2：GET 端点只按 id 主键查，UI 传的是 server_identifier

- 绕过前端用 API 创建后（POST 同端点），`id`（服务端自动生成的 UUID）
  ≠ `server_identifier`（自定义值）；GET 传 `server_identifier` 按 `id` 查 → 恒 400
  "MCP tool not found"（`services/tools/mcp_tools_manage_service.py` 的
  `get_provider` 支持按 `server_identifier` 查，但 GET 端点没有使用该参数）。
- **绕法**：把 `server_identifier` 更新为与 `id` 一致。

### 2.3 重建步骤（换机/重装时照做）

```bash
# 0) 确认版本；≥1.18 先试 UI 创建
# 1) 用浏览器 Console 绕过前端（UI 创建会挂坑 1）。
#    需要 CSRF：cookie 名 csrf_token → header X-CSRF-Token
#    粘贴到 Dify 页面 F12 Console（浏览器会话自动带登录态与 CSRF）：
fetch('/console/api/workspaces/current/tool-provider/mcp', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': document.cookie.split('; ').find(c => c.startsWith('csrf_token='))?.split('=')[1] },
  body: JSON.stringify({
    server_url: 'http://<YOUR_SERVER_IP>:<YOUR_PORT>/mcp',
    name: 'skills-hub',
    icon: '', icon_type: 'emoji', icon_background: '#E0F2FE',
    server_identifier: '<生成的 UUID，如 8b381d14-9120-4d2f-8963-9e4015dd01dc>',
    headers: { Authorization: 'Basic <base64(user:pass)>' }   // 凭据见本地 cloud-services.md
  })
}).then(r => r.json()).then(d => console.log(d))

# 2) 同步 id（坑 2 绕法），容器名/库名按实际替换：
docker exec <postgres容器> psql -U <user> -d <db> \
  -c "UPDATE tool_mcp_providers SET server_identifier = id WHERE name='skills-hub';"

# 3) 刷新 Dify，MCP 服务器应显示并拉到 4 个工具
```

### 2.4 关键实现位置（后续版本对比修复情况用）

- 前端校验：`web/app/components/tools/mcp/hooks/use-mcp-modal-form.ts`（`isValidServerID`）
- 后端查询：`api/services/tools/mcp_tools_manage_service.py`（`get_provider`）
- GET 路由：`api/controllers/console/workspace/tool_providers.py`（`ToolMCPDetailApi`，仅按 `provider_id`=id 查）
- 请求/响应实体：`api/controllers/console/workspace/tool_providers.py`（`MCPProviderBasePayload`，`server_identifier: str` 无 pattern）
- 认证：console API 需登录态 + CSRF（cookie `csrf_token` → header `X-CSRF-Token`）

## 3. 通用建议

- 标识规则因客户端而异：Claude Code / Coze 任意唯一名即可；**Dify 必须 UUID 且与 id 同步**
- 全部走 HTTP Basic；不要把凭据写进公开仓库
- 变更 skill 内容后，MCP 服务器侧 `refresh_cache` 清缓存，客户端即可拉到新规则
