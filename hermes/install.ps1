<#
.SYNOPSIS
    把 skills-hub 的 skills 安装到 Hermes，与 claude/（Claude Code 客户端）结构完全对等。
    实现方案 B（复制）：把 skills/ 下每个含 SKILL.md 的目录复制到 Hermes 的 skills 目录
    （$HERMES_HOME/skills，未设置时回退 ~/.hermes/skills）。

.DESCRIPTION
    与 claude/install.ps1 对等：
    - claude/install.ps1 → Claude Code 的 ~/.claude/skills
    - hermes/install.ps1 → Hermes 的 $HERMES_HOME/skills
    方案 A（tap）与方案 C（MCP config.yaml）不需要脚本（Hermes 无 CLI 注册命令），
    见 hermes/README.md。

.EXAMPLE
    # 安装到 $HERMES_HOME/skills（未设置则 ~/.hermes/skills）
    powershell -ExecutionPolicy Bypass -File hermes/install.ps1

    # 指定目录 + 覆盖已存在
    powershell -ExecutionPolicy Bypass -File hermes/install.ps1 -TargetDir "$env:HERMES_HOME\skills" -Force
#>
[CmdletBinding()]
param(
    [string]$TargetDir = "",

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
    $root = Split-Path -Parent $RepoDir   # hermes/ -> 仓库根
    $src = Join-Path $root "skills"
    if (-not (Test-Path -LiteralPath $src)) {
        throw "未找到 skills 目录: $src"
    }
    return $src
}

function Get-HermesSkillsDir {
    $hh = $env:HERMES_HOME
    if ($hh) {
        return Join-Path $hh "skills"
    }
    return Join-Path $HOME ".hermes\skills"
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
$target = if ($TargetDir) { $TargetDir } else { Get-HermesSkillsDir }
New-Item -ItemType Directory -Path $target -Force | Out-Null
$result = Copy-Skills -Source $src -Target $target -Force:$Force

Write-Host ""
Write-Host "=== skills 安装结果 → $target ===" -ForegroundColor Cyan
foreach ($n in $result.installed) { Write-Host "  [installed] $n" -ForegroundColor Green }
foreach ($n in $result.skipped) { Write-Host "  [skipped]   $n (已存在，用 -Force 覆盖)" -ForegroundColor Yellow }

Write-Host ""
Write-Host "=== 验证 ===" -ForegroundColor Cyan
Write-Host "  1. hermes skills list          # 应看到 4 个 enabled skills"
Write-Host "  2. 重启 Hermes 会话后，在对话中描述任务即可自动加载对应 skill"
Write-Host "  3. 方案 A（tap）/ 方案 C（MCP config）见 hermes/README.md"
