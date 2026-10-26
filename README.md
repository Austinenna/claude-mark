# mark：Claude Code 会话书签

对话告一段落、以后可能还要接着用时，在会话里输入 `/mark` 存一个书签。之后在终端运行 `mark`，选中书签按回车，就会回到那个会话。

- **会话里** `/mark [备注]`：Claude 写下标题、摘要、下一步和标签，脚本记下会话 ID 和启动目录。同一会话再次 `/mark` 会更新这条书签。
- **终端里** `mark`：用 fzf 列出书签，输入文字筛选。回车进入会话，ctrl-d 删除，ctrl-y 复制恢复命令。
- **可选 AI 检索**：配置一个 OpenAI 兼容接口后，`mark 关键词` 会让模型按意思查找，记不清原话也能找到。

## 前置准备

| 准备 | 是否必须 | 说明 |
|---|---|---|
| Claude Code | 必须 | 较新版本，会话里要有 `CLAUDE_CODE_SESSION_ID` 环境变量 |
| Python 3.9+ | 必须 | macOS 自带的 `/usr/bin/python3`（3.9）就够用，只用标准库 |
| fzf | 终端查找时需要 | macOS：`brew install fzf`；Linux：`apt install fzf` 等。没有 fzf 时只能用 `mark ls` 和 `mark rm <ID>` |
| `~/.local/bin` 在 PATH 里 | 必须 | macOS 默认不在 PATH 里。在 `~/.zshrc` 里加一行 `export PATH="$HOME/.local/bin:$PATH"` |
| 剪贴板工具 | 可选 | ctrl-y 复制用。macOS 自带 `pbcopy`；Linux 用 `wl-copy`、`xclip` 或 `xsel`。都没有时直接把命令打印出来 |
| AI 接口 | 可选 | 见下文“AI 检索” |

支持 macOS 和 Linux。Windows 不支持（软链接安装和直接进入会话的方式都不一样）。

## 安装

1. 把仓库克隆到 Claude Code 的 skill 目录：
   ```
   git clone https://github.com/Austinenna/claude-mark.git ~/.claude/skills/mark
   ```
2. 打开 Claude Code，在任意会话里输入 `/mark`。第一次存书签时，脚本会建好 `~/.local/bin/mark` 链接，回复里会提示“已安装终端命令 mark”。
3. 打开一个新终端，运行 `mark`。

如果 `~/.local/bin/mark` 已经被别的程序占用，脚本不会覆盖，会在回复里提示。

更新：`git -C ~/.claude/skills/mark pull`。终端命令是链接，更新后自动生效。

## 终端命令

```
mark                 打开书签列表：输入文字筛选，右侧预览摘要和下一步
                       回车 进入会话 · ctrl-d 删除 · ctrl-y 复制恢复命令 · esc 退出
mark 关键词           带关键词打开；配置了 AI 时先由 AI 按意思筛选排序
mark --no-ai 关键词   不用 AI，只按关键词筛选
mark ls              打印全部书签和恢复命令
mark rm [ID前缀]      删除书签；不带 ID 时打开列表选择
```

进入会话时，脚本会先切换到会话启动时的目录，再运行 `claude --resume <ID>`。退出 Claude 后，终端回到原来的目录。

## AI 检索（可选）

新建 `~/.config/mark/ai.env`，写入任意一个 OpenAI Chat Completions 兼容的接口：

```
MARK_AI_BASE_URL=https://api.example.com/v1
MARK_AI_API_KEY=sk-...
MARK_AI_MODEL=模型名
```

`MARK_AI_BASE_URL` 写到 `/v1` 为止，脚本会自己加上 `/chat/completions`。建议 `chmod 600 ~/.config/mark/ai.env`。同名环境变量会覆盖文件里的值。

每次带关键词搜索时，所有书签的标题、摘要、下一步、标签、备注、目录名和日期都会发给这个接口，不包含对话内容。选一个便宜、快的模型就够用。没有配置或者调用失败时，自动改为关键词筛选。

## 数据存放位置

| 内容 | 位置 |
|---|---|
| 书签 | `~/.claude/mark/marks.jsonl`，每行一条，可以用环境变量 `CLAUDE_MARK_FILE` 改位置 |
| 终端命令 | `~/.local/bin/mark`，链接到本 skill 的 `scripts/mark.py` |
| AI 配置 | `~/.config/mark/ai.env` |

书签只记录“指向哪个会话”，对话内容仍由 Claude Code 自己保存。Claude Code 默认只保留 30 天的会话记录，过期的书签在列表里标 ⚠️，无法恢复。想保留更久，可以在 `~/.claude/settings.json` 里把 `cleanupPeriodDays` 调大，比如 `365`。

## 卸载

```
rm ~/.local/bin/mark
rm -rf ~/.claude/skills/mark
rm -rf ~/.claude/mark ~/.config/mark   # 连书签和 AI 配置一起删
```
