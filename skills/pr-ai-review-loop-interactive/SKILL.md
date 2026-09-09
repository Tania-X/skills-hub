---
name: pr-ai-review-loop-interactive
description: Interactive (human-in-the-loop) flavor of the AI PR review loop: monitor review findings, auto-fix severity >= 4, bring severity < 4 to the human for a decision, and stop the automatic loop at the 4th review (at most 3 fix rounds) with a termination report. The sibling skill pr-ai-review-loop (skills-hub v3) is the fully automated/headless flavor; this one is for live human-supervised PR review sessions.
---

# AI Review 协作循环（交互版 · pr-ai-review-loop-interactive）

> 适用场景：每次功能分支 push 后，由 AI Review 自动审查 PR，**人在回路中**逐轮拍板。
> 目标：严重问题自动修复，轻微问题不擅自改，交由人来决策。
> 自动化风味对照：skills-hub 的 `pr-ai-review-loop`（v3）是纯自动化/headless 版；本 skill 是交互版——同为循环上限规则，但每一步 < 4 级问题都等人拍板。
> **自动循环有上限：监听至第 4 次评审为止（即最多 3 轮「修复 → 复审」），之后必须终止并汇报，等人工拍板。**

## 工作流

```text
1. push feature 分支
2. 创建 PR 到 main
3. 监听 AI Review 结果（评审轮次计数：PR 打开后的首次评审为第 1 次）
4. 分析严重级别：
   - severity >= 4：直接修复 → push → 回到第 3 步监听（轮次 +1）
   - severity < 4：停下，不擅自修改
5. 对 severity < 4 的问题：
   - 分析是否真的需要修复
   - 给出结论与建议
   - 等人决策后再动手
6. 循环上限：第 4 次评审结果出来后立即终止自动循环（不再自动修、不再 push）
   → 输出「终止报告」（见下），停在此处等人工决定
```

## 严重级别定义

| 级别 | 含义 | 自动处理 |
|---|---|---|
| 5 | 致命 | 是 |
| 4 | 严重 | 是 |
| 3 | 必修 | 否，等人决策 |
| 2 | 轻微 | 否，等人决策 |
| 1 | 建议 | 否，等人决策 |

## 自动修复触发条件

只有同时满足以下条件才自动修复：

```text
- AI Review 标记 severity >= 4
- 修复方案明确、低风险
- 不会引入新的行为变化
```

自动修复后：

```text
git add <files>
git commit -m "fix: <原因>"
git push origin <branch>
```

然后继续监听下一轮 Review（注意轮次计数，见「自动循环上限」）。

## 自动循环上限（第 4 次评审终止）

```text
- 最多进行 3 轮「修复 → push → 复审」；第 4 次评审结果出来后，自动循环到此为止。
- 终止后必须输出「终止报告」，内容：
  1. 各轮评审的严重级别分布与门禁(check)状态
  2. 已修复的问题清单（commit）
  3. 仍未解决、等待人工决策的问题清单（按严重级别排序，若有 severity >= 4/3 必须显著标注）
  4. 结论：可以进入合并流程 / 仍需人工修复后再合并
- 报告后停下，不再自动修改。人认为需要修复时，由人明确指示后再动手。
```

## 非自动修复处理方式

对 severity < 4 的问题：

```text
1. 判断是否为真实问题
2. 判断影响范围
3. 判断是否值得在本次 PR 修复
4. 输出结论：
   - 建议修复 / 可以忽略 / 后续跟进
5. 等人拍板
```

不要因为“AI 说有问题”就擅自改。

## 边界

- 如果 AI Review 卡住或超时，主动查询 check-run 状态。
- 如果 Review 结论与代码事实不符，以代码事实为准，并说明原因。
- 如果问题跨多个 PR 或涉及架构决策，即使 severity >= 4 也可能需要先咨询人，不盲目自动改。
- 到达循环上限（第 4 次评审）时，即使仍有 severity >= 4 问题，也不再自动修——在终止报告中显著标出并等人工决策。

## 连续修不完严重问题时：Review 逻辑改进（提意见）

正常情况下，前 1~3 轮就应把严重问题（>= 4，含多数必修 3 级）清完。若直到上限仍未清完，或同一类问题反复出现，应主动给人提 review 逻辑/流程改进意见，例如：

```text
1. 噪音/误报诊断：是否因缺少上下文（事件契约、设计意图、架构约定）导致 reviewer 反复标记
   "设计意图类"问题 → 在代码注释或仓库 docs 里补上下文，或 .ai-review.yaml 的 review_focus 里补充说明
2. PR 切片：改动过大导致单批 token 超限、审不细 → 拆小 PR、或调 max_files_per_batch / max_lines_per_file
3. 阈值校准：反复出现大量轻微级噪音 → 调高 min_severity 或 require_fix_severity，只留真正门禁项
4. 重复标记同一语义问题：多为事件契约/设计取舍未固化 → 用架构说明文档喂给 review，而不是改代码
5. 模型与成本：可考虑换更强模型或只对高风险文件精审（review_focus + ignore_paths 收紧）
```

意见应具体到「哪类问题 × 建议动作」，由人决定是否采纳，不擅自改 .ai-review.yaml。

## 附加约定（2026-09-04）

- feature 分支合并后永不删除。
- PR 合并使用普通 merge（merge commit），不使用 squash merge。
- 禁止直接 push main；开发必须走 feature 分支 + PR。
