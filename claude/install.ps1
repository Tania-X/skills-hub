<#
.SYNOPSIS
    把 skills-hub 的 skills 安装到 Claude Code，并可选择注册 MCP 服务器。
    与 Hermes 方案 B（复制）/ 方案 C（MCP）完全对等。

.DESCRIPTION
    - 方案 B（复制）：把仓库 skills/ 下每个含 SKILL.md 的目录复制到 Claude Code 的
      skills 目录（个人级 ~/.claude/skills，或项目级 ./.claude/skills），
      Claude Code 启动时自动发现、按需加载。
    - 方案 C（MCP）：`claude mcp add skills-hub`，注册本仓库的 MCP 服务器；
      通过 SKILLS_HUB_INSTALL_DIR 把 install_skill 的写入目标指向 Claude 的 skills 目录。

.EXAMPLE
    # Windows：安装到个人级 ~/.claude/skills 并注册 MCP
    powershell -ExecutionPolicy Bypass -File claude/install.ps1 -RegisterMcp

    # 只复制，不注册 MCP
    powershell -ExecutionPolicy Bypass -File claude/install.ps1

    # 安装到当前项目 .claude/skills
    powershell -ExecutionPolicy Bypass -File claude/install.ps1 -Scope project

    # 覆盖已存在的 skill
    powershell -ExecutionPolicy Bypass -File claude/install.ps1 -Force
#>
[CmdletBinding()]
param(
    [ValidateSet("user", "project")]
    [string]$Scope = "user",

    [string]$TargetDir = "",

    [switch]$RegisterMcp,

    [switch]$Force,

    [string]$RepoDir = ""
)

$ErrorActionPreference = "Stop"

# 注意：$PSScriptRoot 在 param 默认值求值时还是空的，必须进入函数体后再取。
if (-not $RepoDir) {
    $RepoDir = $PSScriptRoot
}

function Get-SkillsSource {
    param([string]$RepoDir)
    $root = Split-Path -Parent $RepoDir   # claude/ -> 仓库根
    $src = Join-Path $root "skills"
    if (-not (Test-Path -LiteralPath $src)) {
        throw "未找到 skills 目录: $src"
    }
    return $src
}

function Get-InstallTarget {
    param([string]$Scope, [string]$TargetDir)
    if ($TargetDir) {
        return $TargetDir
    }
    if ($Scope -eq "user") {
        return Join-Path $HOME ".claude\skills"
    }
    return Join-Path (Get-Location) ".claude\skills"
}

function Copy-Skills {
    param([string]$Source, [string]$Target, [switch]$Force)
    $installed = @()
    $skipped = @()
    foreach ($child in Get-ChildItem -LiteralPath $Source -Directory) {
        $skillMd = Join-Path $child.FullName "SKILL.md"
        if (-not (Test-Path -LiteralPath $skillMd)) { continue }
        $dest = Join-Path $Target $child.Name
        if (Test-Path -LiteralPath $dest) {
            if (-not $Force) {
                $skipped += $child.Name
                continue
            }
            Remove-Item -LiteralPath $dest -Recurse -Force
        }
        Copy-Item -LiteralPath $child.FullName -Destination $dest -Recurse
        $installed += $child.Name
    }
    return @{ installed = $installed; skipped = $skipped }
}

# ---------------------------------------------------------------- main

$src = Get-SkillsSource $RepoDir
$target = Get-InstallTarget $Scope $TargetDir
New-Item -ItemType Directory -Path $target -Force | Out-Null
$result = Copy-Skills -Source $src -Target $target -Force:$Force

Write-Host ""
Write-Host "=== skills 安装结果 → $target ===" -ForegroundColor Cyan
foreach ($n in $result.installed) { Write-Host "  [installed] $n" -ForegroundColor Green }
foreach ($n in $result.skipped) { Write-Host "  [skipped]   $n (已存在，用 -Force 覆盖)" -ForegroundColor Yellow }

if ($RegisterMcp) {
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if (-not $claude) {
        Write-Warning "未找到 claude 命令（先安装 Claude Code：npm install -g @anthropic-ai/claude-code）。skills 已复制，MCP 注册跳过。"
    } else {
        $mcpScript = Join-Path (Split-Path -Parent $RepoDir) "mcp\mcp_server.py"
        if (-not (Test-Path -LiteralPath $mcpScript)) { throw "未找到 MCP server: $mcpScript" }
        Write-Host ""
        Write-Host "=== 注册 MCP: skills-hub → $mcpScript ===" -ForegroundColor Cyan
        & claude mcp remove skills-hub 2>$null | Out-Null
        & claude mcp add skills-hub --env "SKILLS_HUB_INSTALL_DIR=$target" -- python "$mcpScript"
        if ($LASTEXITCODE -ne 0) {
            throw "claude mcp add 失败 (exit $LASTEXITCODE)"
        }
    }
}

Write-Host ""
Write-Host "=== 验证 ===" -ForegroundColor Cyan
Write-Host "  1. claude mcp list          # 应看到 skills-hub"
Write-Host "  2. 重启 Claude Code 会话（skills 在启动时扫描）"
Write-Host "  3. 提问「列出可用 skills」或直接说「执行 pr-ai-review-loop 工作流」"
