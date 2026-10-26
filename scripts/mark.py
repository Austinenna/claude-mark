#!/usr/bin/env python3
"""mark —— Claude Code 会话书签。

存书签（由 /mark skill 在会话里调用）：
  mark.py add [--id ID]     从 stdin 读 JSON（title/summary/next/tags/note），按会话 ID 新增或更新

终端里查找、恢复、删除：
  mark [关键词...]           打开书签列表（fzf）。回车进入会话，ctrl-d 删除，ctrl-y 复制恢复命令
                            配置了 AI 时，带关键词会先让 AI 按意思筛选排序
  mark --no-ai 关键词        不用 AI，只按关键词模糊筛选
  mark ls                   直接打印全部书签
  mark rm [ID前缀]           删除书签；不带 ID 时打开列表选

文件：
  书签   ~/.claude/mark/marks.jsonl（CLAUDE_MARK_FILE 可覆盖）
  AI     ~/.config/mark/ai.env 或同名环境变量：MARK_AI_BASE_URL、MARK_AI_API_KEY、MARK_AI_MODEL
         （OpenAI Chat Completions 兼容；BASE_URL 写到 /v1 为止）。不配置就不用 AI
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

HOME = Path.home()
MARK_FILE = Path(os.environ.get("CLAUDE_MARK_FILE", HOME / ".claude/mark/marks.jsonl")).expanduser()
AI_FILE = HOME / ".config/mark/ai.env"
PROJECTS = HOME / ".claude/projects"
BIN_LINK = HOME / ".local/bin/mark"
SELF = Path(__file__).resolve()
FIELDS = ("title", "summary", "next", "tags", "note")


def die(msg):
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(1)


def warn(msg):
    print(msg, file=sys.stderr)


# ---------- 书签文件 ----------

def load():
    if not MARK_FILE.exists():
        return []
    return [json.loads(l) for l in MARK_FILE.read_text().splitlines() if l.strip()]


def save(marks):
    MARK_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = MARK_FILE.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in marks))
    tmp.replace(MARK_FILE)


def sorted_marks():
    return sorted(load(), key=lambda m: m.get("updated", ""), reverse=True)


def find(marks, key):
    hits = [m for m in marks if m["id"].startswith(key)]
    if not hits:
        die(f"没有 ID 以 {key} 开头的书签")
    if len(hits) > 1:
        die(f"{key} 对应多个书签，请写长一点")
    return hits[0]


def transcript(sid):
    hits = list(PROJECTS.glob(f"*/{sid}.jsonl"))
    return hits[0] if hits else None


def session_cwd(path):
    """会话启动时的目录。claude --resume 要在这个目录下运行才能找到会话。"""
    with path.open() as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("cwd"):
                return d["cwd"]
    return None


def resume_cmd(m):
    return f"cd {shlex.quote(m['cwd'])} && claude --resume {m['id']}"


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------- add：由 skill 调用 ----------

def ensure_link():
    """第一次存书签时把终端命令 mark 链到本脚本。

    开发副本（skill 目录的上一级叫 dev）或设置了 MARK_NO_LINK 时不建，
    免得终端命令指向还没发布的代码。
    """
    if SELF.parents[2].name == "dev":
        return "skipped: 开发副本，不建终端链接"
    if os.environ.get("MARK_NO_LINK"):
        return "skipped: 设置了 MARK_NO_LINK，不建终端链接"
    if BIN_LINK.is_symlink() and BIN_LINK.resolve() == SELF:
        return "exists"
    if BIN_LINK.exists() or BIN_LINK.is_symlink():
        old = os.readlink(BIN_LINK) if BIN_LINK.is_symlink() else None
        if not (old and old.endswith("/mark/scripts/mark.py")):
            return f"conflict: {BIN_LINK} 已存在且不是本脚本的链接，未覆盖"
        BIN_LINK.unlink()  # 指向别处（旧位置）的本脚本链接，更新它
    BIN_LINK.parent.mkdir(parents=True, exist_ok=True)
    BIN_LINK.symlink_to(SELF)
    in_path = str(BIN_LINK.parent) in os.environ.get("PATH", "").split(":")
    return "installed" if in_path else f"installed: 但 {BIN_LINK.parent} 不在 PATH 里"


def cmd_add(args):
    sid = args[args.index("--id") + 1] if "--id" in args else os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        die("拿不到会话 ID：请用 --id 传入")
    path = transcript(sid)
    if not path:
        die(f"在 {PROJECTS} 下找不到会话 {sid} 的记录")
    data = json.loads(sys.stdin.read() or "{}")
    marks = load()
    old = next((m for m in marks if m["id"] == sid), None)
    mark = old or {"id": sid, "created": now()}
    mark["cwd"] = session_cwd(path) or mark.get("cwd")
    for k in FIELDS:
        if data.get(k):
            mark[k] = data[k]
    mark["updated"] = now()
    if not old:
        marks.append(mark)
    save(marks)
    out = {"action": "updated" if old else "added", **mark, "resume": resume_cmd(mark), "terminal": ensure_link()}
    print(json.dumps(out, ensure_ascii=False, indent=2))


# ---------- AI 检索（可选） ----------

def ai_config():
    cfg = {}
    if AI_FILE.exists():
        for line in AI_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip().removeprefix("export ").strip()] = v.strip().strip("'\"")
    for k in ("MARK_AI_BASE_URL", "MARK_AI_API_KEY", "MARK_AI_MODEL"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    if cfg.get("MARK_AI_BASE_URL") and cfg.get("MARK_AI_API_KEY") and cfg.get("MARK_AI_MODEL"):
        return cfg
    return None


def ai_rank(marks, query, cfg):
    """把全部书签和关键词发给模型，返回按相关度排序的书签；出错返回 None。"""
    brief = [
        {"id": m["id"], "date": m.get("updated", "")[:10], "dir": Path(m.get("cwd", "")).name,
         **{k: m[k] for k in FIELDS if m.get(k)}}
        for m in marks
    ]
    prompt = (
        "下面是用户的会话书签列表（JSON）。用户想找的会话描述是：\n"
        f"「{query}」\n\n"
        "用户往往记不清原话，可能用近义词、换一种说法、只记得一个侧面，或者中英混用。"
        "按意思判断每条书签是否相关，只保留确实相关的，最相关的排在前面，宁可多给一两条边缘候选也不要漏掉。\n"
        '只输出 JSON，格式：{"ids": ["书签id", ...]}，没有相关的就输出 {"ids": []}。\n\n'
        + json.dumps(brief, ensure_ascii=False)
    )
    body = json.dumps({
        "model": cfg["MARK_AI_MODEL"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        cfg["MARK_AI_BASE_URL"].rstrip("/") + "/chat/completions", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['MARK_AI_API_KEY']}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            content = json.load(r)["choices"][0]["message"]["content"]
        ids = json.loads(re.search(r"\{.*\}", content, re.S).group(0))["ids"]
    except Exception as e:  # 网络、鉴权、模型输出格式都可能出错，统一退回普通筛选
        warn(f"AI 检索失败（{type(e).__name__}: {e}），改用关键词筛选")
        return None
    by_id = {m["id"]: m for m in marks}
    return [by_id[i] for i in ids if i in by_id]


# ---------- 终端交互 ----------

def line(m):
    flag = "" if transcript(m["id"]) else "⚠️ "
    return f"{m['id']}\t{flag}{m.get('updated', '')[5:10]} · {Path(m.get('cwd', '')).name} · {m.get('title', '(无标题)')}"


def cmd_preview(args):
    m = find(load(), args[0])
    lost = "" if transcript(m["id"]) else "\n⚠️ 会话记录已被清理，无法恢复\n"
    print(f"{m.get('title', '')}\n{lost}")
    print(f"时间  {m.get('updated', '')[:16].replace('T', ' ')}")
    print(f"目录  {m.get('cwd', '')}")
    if m.get("tags"):
        print(f"标签  {', '.join(m['tags'])}")
    for k, name in (("summary", "摘要"), ("next", "下一步"), ("note", "备注")):
        if m.get(k):
            print(f"\n{name}\n{m[k]}")
    print(f"\n{resume_cmd(m)}")


def pick(marks, query="", header=""):
    """用 fzf 选一条，返回 (按键, 书签)；取消返回 (None, None)。"""
    if not shutil.which("fzf"):
        die("没找到 fzf：macOS 用 brew install fzf，Linux 用包管理器安装（如 apt install fzf）。不装也可以用 mark ls / mark rm <ID>")
    preview = f"{shlex.quote(sys.executable)} {shlex.quote(str(SELF))} _preview {{1}}"
    proc = subprocess.run(
        ["fzf", "--delimiter=\t", "--with-nth=2..", "--query", query, "--expect=ctrl-d,ctrl-y",
         "--preview", preview, "--preview-window=right,50%,wrap", "--header", header, "--tiebreak=index"],
        input="\n".join(line(m) for m in marks), stdout=subprocess.PIPE, text=True,
    )
    out = proc.stdout.splitlines()
    if proc.returncode != 0 or len(out) < 2:
        return None, None
    sid = out[1].split("\t", 1)[0]
    return out[0] or "enter", next(m for m in marks if m["id"] == sid)


def copy(text):
    """复制到剪贴板；找不到剪贴板工具返回 False，由调用方直接打印。"""
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if shutil.which(cmd[0]):
            return subprocess.run(cmd, input=text, text=True).returncode == 0
    return False


def delete(m, ask=True):
    if ask:
        try:
            ok = input(f"删除书签「{m.get('title', m['id'])}」？[y/N] ").strip().lower() == "y"
        except EOFError:
            ok = False
        if not ok:
            return False
    save([x for x in load() if x["id"] != m["id"]])
    print(f"已删除：{m.get('title', m['id'])}")
    return True


def resume(m):
    if not transcript(m["id"]):
        die("这个会话的记录已经被清理，无法恢复")
    if not Path(m["cwd"]).is_dir():
        die(f"会话目录不存在了：{m['cwd']}")
    os.chdir(m["cwd"])
    os.execvp("claude", ["claude", "--resume", m["id"]])


def cmd_browse(args):
    use_ai = "--no-ai" not in args
    query = " ".join(a for a in args if a != "--no-ai")
    marks = sorted_marks()
    if not marks:
        print("还没有书签。在 Claude Code 会话里输入 /mark 存一个。")
        return
    fzf_query, header = query, "回车 进入会话 · ctrl-d 删除 · ctrl-y 复制恢复命令"
    cfg = ai_config() if (query and use_ai) else None
    if cfg:
        print(f"AI 检索中：{query} …", file=sys.stderr)
        ranked = ai_rank(marks, query, cfg)
        if ranked is not None:
            if not ranked:
                print(f"AI 没找到和「{query}」相关的书签，下面是全部书签。", file=sys.stderr)
            else:
                marks, fzf_query = ranked, ""
                header = f"AI 按「{query}」筛出 {len(ranked)} 条 · " + header
    while True:
        key, m = pick(marks, fzf_query, header)
        if not m:
            return
        if key == "ctrl-d":
            if delete(m):
                marks = [x for x in marks if x["id"] != m["id"]]
                if not marks:
                    return
            continue
        if key == "ctrl-y":
            cmd = resume_cmd(m)
            print(f"已复制：{cmd}" if copy(cmd) else cmd)
            return
        resume(m)


def cmd_ls(args):
    marks = sorted_marks()
    if not marks:
        print("还没有书签。")
    for m in marks:
        print(line(m).split("\t", 1)[1])
        print(f"   {resume_cmd(m)}")


def cmd_rm(args):
    marks = load()
    if args:
        delete(find(marks, args[0]), ask=False)
        return
    _, m = pick(sorted_marks(), header="选择要删除的书签")
    if m:
        delete(m)


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else ""
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
    elif cmd == "add":
        cmd_add(args[1:])
    elif cmd == "_preview":
        cmd_preview(args[1:])
    elif cmd == "ls":
        cmd_ls(args[1:])
    elif cmd == "rm":
        cmd_rm(args[1:])
    else:
        cmd_browse(args)


if __name__ == "__main__":
    main()
