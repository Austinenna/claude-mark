---
name: mark
description: 给当前 Claude Code 会话加书签（或更新已有书签），记下标题、摘要、下一步和恢复命令，之后在终端用 `mark` 命令查找、恢复、删除。用户输入 `/mark [备注]`，或说“记下这个对话”“这个会话以后还要用”“给这个会话打个标记”时使用。查找和恢复不在会话里做，告诉用户在终端运行 `mark`。
argument-hint: "[备注]"
---

# mark：存会话书签

这个 skill 只做一件事：把当前会话存成书签，或者更新它。查找、恢复、删除由终端命令 `mark` 负责，不在会话里做。

脚本：本 skill 目录下的 `scripts/mark.py`，下文写作 `mark.py`。调用时用完整路径，以 `python3` 运行，只用标准库。
书签文件：`~/.claude/mark/marks.jsonl`，只通过脚本读写。

## 步骤

1. 回顾整段对话，写出：
   - `title`：12～20 字，说清这次在做什么，日后一眼能认出
   - `summary`：2～3 句，做到了哪一步，关键结论或决定是什么
   - `next`：下次接着做什么；没有后续就写“无，仅备查”
   - `tags`：1～3 个短标签（项目名、主题）
   - `note`：`$ARGUMENTS` 的原文（用户的备注），没有就省略
   同一会话再次 `/mark` 时，按最新进展重写这几项。脚本会更新原书签，不会新增。
2. 用 heredoc 把 JSON 传给脚本。会话 ID 由脚本从环境变量 `CLAUDE_CODE_SESSION_ID` 读取，工作目录由脚本从会话记录读取，都不要自己填：
   ```bash
   python3 <skill目录>/scripts/mark.py add <<'EOF'
   {"title": "...", "summary": "...", "next": "...", "tags": ["..."], "note": "..."}
   EOF
   ```
   如果脚本报“拿不到会话 ID”，加上 `--id ${CLAUDE_SESSION_ID}` 重试。
3. 回复用户两三行：
   ```
   已标记：<title>（或：已更新：<title>）
   终端运行 mark 查找和恢复；直接恢复：cd <cwd> && claude --resume <id>
   ```

## 终端命令 `mark` 的安装规则

用户要用终端命令 `mark`，之前一定先在会话里 `/mark` 过，所以**由第一次存书签负责安装**。`mark.py add` 每次运行都会检查 `~/.local/bin/mark`，结果写在返回 JSON 的 `terminal` 字段里：

| `terminal` | 含义 | 回复里怎么说 |
|---|---|---|
| `installed` | 刚建好链接，指向本 skill 的 `scripts/mark.py` | 加一句：“已安装终端命令 `mark`，在新终端里就能用” |
| `exists` | 链接已经在 | 不提 |
| `installed: …不在 PATH 里` | 链接建了，但 `~/.local/bin` 不在 PATH 里 | 告诉用户把 `~/.local/bin` 加进 PATH |
| `conflict: …` | `~/.local/bin/mark` 已被别的东西占用，脚本没有覆盖 | 原样告诉用户，让用户决定，不要自己删 |
| `skipped: …` | 从开发副本运行（skill 目录的上一级叫 `dev`），或设置了 `MARK_NO_LINK`，不建链接 | 不提 |

不要手动去建或者改这个链接，交给脚本处理。安装要求和前置准备见本目录的 `README.md`。

## 终端命令速查（用户问起时告诉用户）

```
mark              打开书签列表（fzf）：输入文字筛选，右侧预览摘要
                    回车 进入会话 · ctrl-d 删除 · ctrl-y 复制恢复命令 · esc 退出
mark 关键词        有关键词：配置了 AI 就先让 AI 按意思筛选排序，没配置就按关键词模糊筛选
mark --no-ai 关键词  不用 AI
mark ls           直接打印全部书签
mark rm [ID]      删除书签
```

AI 检索是可选功能，配置写在 `~/.config/mark/ai.env`（`MARK_AI_BASE_URL`、`MARK_AI_API_KEY`、`MARK_AI_MODEL`，使用 OpenAI Chat Completions 兼容接口）。没有这个配置文件时，自动只用 fzf。凭证不放在 skill 目录里。

## 注意

- `claude --resume` 只能在会话启动时的目录里找到会话，所以恢复时要先 `cd` 过去。`cwd` 由脚本从会话记录读取，不要用当前的 `pwd`。
- 会话记录会按 `settings.json` 的 `cleanupPeriodDays` 清理。被清理的书签在终端列表里标 ⚠️，无法恢复。
