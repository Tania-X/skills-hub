---
name: pr-ai-review-loop
description: "Push → 发起 PR → 监听 CI/AI review → 按意见循环改进 的完整工作流（三角色版 v3）。当项目接了 AI PR review（PR 打开/更新时自动审 diff），且用户说「push / 提 PR / 发起 PR」时使用。核心：代码改完先不 push、主动待命汇报，等用户明确指令才 push；push 后自动发 PR、盯 CI 与 AI review；评审环节（Reviewer）与裁决环节（Judge）可插拔——默认加载 ai-review-method skill 执行评审；循环硬上限 3 轮，之后强制人工介入。"
version: 3.0.0
author: Hermes Agent + Tania-X
license: MIT
platforms: [windows, linux, macos]
dependencies: [ai-review-method, review-severity-policy]
metadata:
  hermes:
    tags: [github, pr, ci, ai-review, workflow, loop, multi-agent]
    related_skills: [ai-review-method, review-severity-policy, github-auth, github-pr-workflow]
---

# PR + AI Review 循环工作流（三角色版 v3）

## 三角色模型（本版核心）

```
┌─ Coder（改代码）──────────────┐  ┌─ Reviewer（评审）────────────┐  ┌─ Judge（裁决）────────────┐
│  · 执行代码修改、本地验证、push │  │  · 审 diff → 产出 issues      │  │  · 对 issues 逐条裁决       │
│  · 可插拔：角色描述/风格/约束   │  │  · 可插拔：默认 ai-review-method│  │  · 决定保留/降级/删除       │
│   可配置                        │  │    skill，可换 ai-tools action│  │  · 输出必修/忽略/待定清单   │
└────────────────────────────────┘  └──────────────────────────────┘  └────────────────────────────┘
```

**角色分离原则**：Coder 不裁决自己写的代码（避免自评偏差）；Reviewer 只评审不修改；Judge 独立裁决。三者通过「裁决清单」交接，互不越权。

## 状态机总览

```
状态 0 ── Coder 代码修改中（不动任何 git 操作）
   │  改完了
   ▼
状态 1 ── 待命：Coder 主动汇报"代码完成 + 本地验证通过，等你指令 push"
   │  （interactive 模式：等人指令；headless 模式：自动继续）
   │  用户说 push / 提 PR（或 headless 自动）
   ▼
状态 2 ── Coder: push + 创建 PR（一次性动作）
   │  自动
   ▼
状态 3 ── 监听 CI + Reviewer 评审（后台轮询，不打扰用户）
   │  review 出结果，自动
   ▼
状态 4 ── Judge 裁决：对 reviewer 的 issues 逐条判定
   │  输出必修清单 / 忽略清单 / 待定清单
   ├─ 必修非空（未超上限）→ 状态 5
   └─ 必修为空 / 已超上限 → 状态 6
   ▼
状态 5 ── Coder 只修"必修"→ 本地验证 → push → 回到状态 3（轮数 +1）
   ▼
状态 6 ── 停止：收尾汇报 / 人工介入报告
   │  interactive → 汇报给用户等裁决
   │  headless → 把报告作为响应返回调用方，中断（不自动恢复）
```

## 角色定义（可插拔配置）

### Coder（默认 = 当前执行 agent）

```yaml
coder:
  role: "当前执行 agent（Hermes / Claude Code / 任意支持 SKILL.md 的 agent）"
  mode: "interactive"          # interactive | headless（见下）
  style: "遵循项目规范（AGENTS.md / 代码风格）；最小改动原则；改完必须本地验证"
  constraints:
    - "只修 Judge 裁决的『必修』项，不擅自扩大范围"
    - "不裁决评审意见的合理性（那是 Judge 的职责）"
    - "commit message 清晰描述改动与理由"
```

**Coder 两种模式（交互式 / 非交互式）**：

| 模式 | 适用场景 | 行为 |
|---|---|---|
| `interactive`（默认） | 本地 Hermes / 人在场 | 代码改完**不 push，主动待命汇报**，等用户明确指令；需要人介入时停下等人 |
| `headless`（非交互式） | webhook 云端触发 / 无人值守 | 全自动执行：push → 评审 → 裁决 → 修复 → 再 push（≤3 轮）；**一旦需要人介入**（3 轮超限 / 异常信号 / 必修项涉及设计意图），**立即中断**，把「人工介入报告」作为**响应返回给调用方**，不等待 |

**headless 模式的铁律豁免**：交互模式的"push 等指令"在 headless 下不适用（自动化流程需要全自动）；但 **headless 一旦中断，绝不自动恢复**——必须等调用方（人或系统）显式再触发。

**插拔方式**：替换 Coder = 换 role/style/constraints/mode，主流程不变。

### Reviewer（默认 = ai-review-method skill）

```yaml
reviewer:
  provider: "ai-review-method"   # 加载 skills/ai-review-method 执行评审
  fallback: "ai-tools action"    # 或 GitHub Actions 的 pr-review
  context: "按 ai-review-method 的 §二 收集（约定文件 + 代码工具）"
```

**插拔方式**：provider 可换（ai-tools action / 其他评审服务 / 自定义 review skill）。换成 skill 时：加载对应 skill 后按其流程执行（Hermes: `skill_view`；Claude Code: skill 在 `~/.claude/skills` 自动发现，按需引用其内容）。

### Judge（默认 = 质量门裁决，新增角色）

```yaml
judge:
  provider: "质量门（ai-review-method §六）"  # 逐条验证 + 降级哨兵
  independent: true    # 独立于 Coder 的决策视角
  severity_policy: "review-severity-policy"   # 严重度策略插件
```

**Judge 裁决输出格式**（Coder 唯一可执行的输入）：
```
必修清单（fix）：[{file, line, issue, action}]   ← Coder 必须修
忽略清单（ignore）：[{file, line, reason}]        ← 不修，记录理由
待定清单（defer）：[{file, line, reason}]         ← 转人工，或留到下个迭代
```

## 铁律（用户偏好，保留）

1. **代码改好后不 push**。push 必须等用户明确说「push / 发起 PR」。（**headless 模式豁免**：自动化触发时自动继续，见 Coder 配置）
2. **改完主动待命汇报**（状态 1）：告诉用户"代码完成、验证通过、等你指令"。（headless 模式不等待）
3. Push 网络策略：**先走本地代理，失败再直连**（代理地址按环境配置，见下文「网络代理」）。
4. 发起 PR 后**主动监听** CI 与 AI review 结果，不要等用户来问。
5. **三角色不越权**：Coder 不裁决、Reviewer 不修改、Judge 不实现。
6. **循环硬上限 3 轮**（含首轮）：第 3 轮后强制停止，转人工介入（interactive 等用户 / headless 返回调用方）。

## 前置检查

```bash
# 1. 认证：gh 或 git 凭据
gh auth status 2>/dev/null || git credential fill 2>/dev/null
# 没有 gh 时：~/.git-credentials 里应有 https://<user>:<PAT>@github.com
# 2. 确认 remote、分支、与 origin/main 的关系
git remote -v
git status --short
git fetch origin
git log --oneline origin/main..HEAD   # 确认领先提交数合理
```

**分支纪律**：所有工作必须基于 `origin/main`（先 `git fetch origin`，必要时 `git rebase origin/main`），否则 PR 会显示大量无关差异。若本地历史与远程无共同祖先（如从 zip 重建的仓库），用「重建分支」修复：

```bash
git checkout -B <feat-branch> origin/main        # 分支指针移到远程 main
git checkout <old-commit> -- <changed-files...>  # 把改动文件内容取过来
git rm <deleted-files...>                        # 显式删除废弃文件
# 检查纯换行符噪音：git diff --stat -w origin/main HEAD 中 0 行差异的文件要恢复
git checkout origin/main -- <noise-file>         # 剔除噪音
git commit --amend                               # 保持 PR 单 commit
```

**CI 前置自检（push 前必做）**：项目 CI 用 `npm ci` 时，本地必须验证 lock 与 package.json 同步，否则 CI 必挂：

```bash
# 没改 package.json 时 lock 不应出现在 diff 里；若被本地 npm install 重写过，恢复 origin/main 版本：
git checkout origin/main -- package-lock.json
# 用隔离目录验证（避免占用 node_modules 的进程干扰）：
$tmp = "$env:TEMP\lock-check"; New-Item -ItemType Directory -Path $tmp -Force | Out-Null
Copy-Item package.json, package-lock.json $tmp; cd $tmp
npm ci --no-audit --no-fund   # exit 0 才安全
```

## Push（先代理，后直连）

```bash
# 尝试 1：走代理（代理地址按环境替换，见「网络代理」）
git -c http.proxy=http://127.0.0.1:7890 -c https.proxy=http://127.0.0.1:7890 push -u origin <branch>
# 若失败（exit 128 / Could not connect）→ 尝试 2：直连
git push -u origin <branch>
# 仍失败 → 报告网络问题，让用户确认 VPN 状态，不要无限重试
```

> **网络代理**：示例用 `http://127.0.0.1:7890`（Clash 类代理的常见端口）。实际环境按用户机器配置——先探测常见端口（7890/7891/1080/10808 等）是否有进程监听，或直接问用户；也可以检查 `netsh winhttp show proxy` / 环境变量 `HTTP_PROXY`。**不要写死**：每次会话先探测再决定。

## 发起 PR

有 `gh` 时：`gh pr create --base main --head <branch> --title "..." --body "..."`

无 `gh` 时用 GitHub API（token 从 `~/.git-credentials` 提取，不硬编码）：

```bash
$token = (Get-Content "$env:USERPROFILE\.git-credentials" | Select-String 'github.com' | Select-Object -First 1).Line -replace 'https://[^:]+:([^@]+)@.*','$1'
# 先查是否已有同 head 的 PR（避免重复创建）：
curl.exe -s -H "Authorization: token $token" "https://api.github.com/repos/<owner>/<repo>/pulls?head=<owner>:<branch>&state=open"
# 没有则创建（注意：body 含中文时用文件方式传 JSON 避免编码/BOM 问题）：
$bodyFile = "$env:TEMP\pr-body.json"
# 用 Set-Content -Encoding ascii -NoNewline 写入纯 ASCII JSON（中文先转义），
# 或用 ConvertTo-Json 后注意 PS5.1 的 utf8 BOM 问题
curl.exe -s -X POST -H "Authorization: token $token" -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" --data-binary "@$bodyFile" \
  "https://api.github.com/repos/<owner>/<repo>/pulls"
```

> 注意：无 gh 时 PR 创建走 api.github.com；push 走 github.com:443。网络策略同样适用（先代理）。
> **踩坑记录**：`ConvertTo-Json | Set-Content -Encoding utf8` 在 PowerShell 5.1 会写 BOM → GitHub 返回 "Problems parsing JSON"。用 `-Encoding ascii -NoNewline` + 纯 ASCII JSON（中文用 \u 转义）。

## 监听 CI / Reviewer 评审

轮询（间隔 30–60s，最多 ~10 分钟；长任务放 background + notify；**响应可能被网络截断**，空响应要重试而不是崩溃）：

```bash
# PR 的 check-runs（AI Review 是其中的 check-run）
# 注意：check-runs 响应很大（含完整 app 对象），网络不稳时易截断——
# 用 -m 120 大超时 + 输出到文件再解析，或用本地已知的 commit SHA 轮询
curl.exe -s -m 120 -H "Authorization: token $token" "https://api.github.com/repos/<owner>/<repo>/commits/<sha>/check-runs" -o "$env:TEMP\checkruns.json"
# PR 的 review 评论（AI review 以 PR comment / review comment 形式发表）
curl.exe -s -H "Authorization: token $token" "https://api.github.com/repos/<owner>/<repo>/pulls/<number>/comments"
curl.exe -s -H "Authorization: token $token" "https://api.github.com/repos/<owner>/<repo>/issues/<number>/comments"
```

**Reviewer 执行**：拿到 diff 后，按配置的 provider 执行评审：
- 默认：加载 `ai-review-method` skill（Hermes: `skill_view`；Claude Code: 自动发现于 skills 目录），按其流程执行（上下文收集 → agentic 代码访问 → 两轴严重度 → 输出 issues JSON）
- 若 provider = ai-tools action：等 GitHub Actions 的评审评论出现即可

## Judge 裁决（状态 4）

拿到 Reviewer 的 issues 后，以独立视角逐条裁决（不修改代码，只判定）：

1. **逐条验证**（按 ai-review-method §六）：
   - 行号存在且属于 diff 新增行 → 保留
   - 假设性证据 + 级别 ≥4 → 降级（按 review-severity-policy 软性参数，默认降到 3）
   - 幻觉（行号不存在/证据对不上）→ 删除
   - 设计意图不明 → 归入待定（defer），转人工
2. **输出三清单**：必修（fix）/ 忽略（ignore + reason）/ 待定（defer + reason）
3. **严重度策略**：加载 `review-severity-policy` skill 获取当前映射规则（可插拔）
4. **哨兵**：若删除/降级比例 >30% → 本轮评审整体质量差 → 触发一次整批重审（带裁决 reasons 作反馈），仍差则降级（check neutral）

**裁决不是"挑刺"**：默认信任 Reviewer 的产出，只在有明确证据时降级/删除。

## 循环改进（成本敏感版 + 轮次上限）

> ⚠️ **成本警告（用户明确要求）**：评审每轮对**全量 diff 重审**，烧 token 约为普通代码评审的 4 倍。追求"零 warn"会无限循环。**够好就停**。

1. **Judge 输出必修清单为空** → 立即停止（不追正文里的"轻微问题/需注意"）
2. **必修项判断**（满足任一才修）：
   - 真 bug / 安全 / 资源问题
   - 违反项目硬性约定（如 AGENTS.md「开发克制(硬性)」）
   - 本次 PR 范围内的逻辑/语义错误
3. **忽略/待定**：记录理由，不 push；待定项明确告诉用户"留到下次"或转人工
4. 修改后：本地验证（构建/测试）→ commit → push（先代理）→ PR 自动重跑 → **轮数 +1**
5. **轮次硬上限：3 轮（含首轮）**。第 3 轮后强制停止，转人工介入，**绝不自作主张继续 push**。
6. **提前停止条件（满足任一即停）**：
   - 必修清单为空
   - 剩余均为忽略/待定（非必修）
   - 连续 2 轮没有新增必修项
   - 用户喊停
7. **可选：更严格的停止判断（异常信号）**——同一问题重复提出 / 意见自相矛盾 / 评分剧烈波动 / 新增问题不降反升时，**考虑**提前终止（非强制，由执行者判断）。
8. 收尾：向用户汇报（几轮、改了什么、**忽略了什么及理由**、待定清单），提示"可以直接合并，warn 不阻塞"。

## 人工介入（轮次上限或异常信号触发）

停止循环后，输出「人工介入报告」并**等用户裁决**：

```
① 每轮评审结论摘要（评分、提了什么）
② Coder 修了什么、为什么修
③ Judge 裁决清单（必修已修 / 忽略+理由 / 待定+理由）
④ 建议的下一步：
   - 继续修（用户明确指示才继续）
   - 带 warn 合并（warn 不阻塞）
   - 调整评审配置（如阈值/模型/严重度策略插件）
   - 其他
```

## 停止条件（汇总）

- Judge 裁决必修清单为空
- 剩余意见均为忽略/待定（非必修）
- **轮次达到 3 轮硬上限**
- **可选**：异常信号确认存在
- 用户喊停

---

## 参考示例（按项目替换）

> 以下是本 skill 在一次实际使用中的项目特定配置（devops-dashboard 项目），**仅作参考**，换项目时全部替换：

- 仓库：`Tania-X/devops-dashboard`，默认分支 `main`，分支习惯 `feat/<功能名>`
- Reviewer provider：`Tania-X/ai-tools/pr-review@main`（GitHub Action，DeepSeek 全量审 diff，error 级阻塞合并）或本地加载 `ai-review-method` skill
- CI：前端 `npm ci && build && lint`（frontend/），后端 Go 测试（backend/）
- 用户身份：`Tania-X <taniax@users.noreply.github.com>`（本地无全局 git 身份时 commit 用 `-c user.name=... -c user.email=...` 带上）
- 代理：`http://127.0.0.1:7890`（iKuuuVPNCore，Clash 类端口）
- git 凭据：`~/.git-credentials`（`https://Tania-X:<PAT>@github.com`，PAT 与 `~/.gh-token` 相同）；系统级 `manager` helper 会弹 GUI，store 有凭据时不会触发
