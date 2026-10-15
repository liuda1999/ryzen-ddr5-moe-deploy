# -*- coding: utf-8 -*-
"""补齐本地缺失的远端提交对象（走 Git Data API，备用通道）。

何时需要它：
    正常用 `git fetch` / `git pull` 即可。但**受限网络下 `github.com:443` 可能被拦截**
    （报 `CONNECT tunnel failed, response 502`），而 `api.github.com` 仍可达。
    此时若别人（或你自己的网页端）在 GitHub 上改过文件，本地就会缺这些提交对象，
    表现为 `git log` 只显示很少几条、`git rev-parse HEAD^^` 直接报
    `fatal: Failed to traverse parents of commit ...`。

它做什么：
    1. 从远端 BRANCH 顶端往下走，收集「本地没有对象」的提交，遇到本地已有的提交就停；
    2. 对每个缺失提交：递归补齐其 tree / subtree / blob（已存在的对象跳过，不重复下载）；
    3. 用 API 返回的元数据在本地重建提交对象，并通过**枚举时区与消息尾换行**
       命中目标 SHA（GitHub 保留写入时的时区，不能想当然按 UTC 重建）；
       命中不了就报错停下，绝不写入一个哈希对不上的对象；
    4. 全部写完后校验 `git cat-file` 能正常遍历。

**已知限制（重要）**：
    **网页端改文件产生的提交是 GitHub 用 GPG 签名的**（committer 为 `GitHub
    <noreply@github.com>`，对象里含 `gpgsig` 头）。这类对象**无法在本地逐字节重建** ——
    API 的 `verification.payload` 是重新序列化过的文本，签名也不保证与对象内一致。
    脚本遇到这种提交会**明确报错并中止**。
    解决办法只有一条：在能访问 `github.com` 的网络里执行 `git fetch origin`。
    （本脚本能补的是「普通未签名提交」，例如自己用 push_via_api.py 推上去的那些。）

安全性：
    - 只”新增“对象，不改写任何已有对象，也不动工作区；
    - 令牌通过 `git credential fill` 现场获取，**不写盘、不打印**；
    - 每个写入的对象都用 `git hash-object -w` 校验哈希 == 远端 SHA，不一致立即报错。

用法：
    python _维护脚本\\pull_via_api.py              # 补齐 main 上的缺失对象
    python _维护脚本\\pull_via_api.py --ref v0.2.7  # 指定 ref（tag / branch）
    python _维护脚本\\pull_via_api.py --dry-run     # 只报告缺了什么，不写入
"""
import hashlib
import itertools
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

OWNER = "liuda1999"
REPO = "ryzen-ddr5-moe-deploy"
API = "https://api.github.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DRY_RUN = "--dry-run" in sys.argv
REF = "main"
for i, a in enumerate(sys.argv):
    if a == "--ref" and i + 1 < len(sys.argv):
        REF = sys.argv[i + 1]

# 枚举用的时区候选：GitHub 保留提交写入时的时区，常见为 UTC 或提交者所在时区
TZS = ["+0000"] + ["%s%02d%02d" % (s, h, m)
                   for h in range(0, 13)
                   for m in (0, 15, 30, 45)
                   for s in ("+", "-")] + ["+1400", "-1200"]


def git(*args, input_bytes=None, check=True):
    p = subprocess.run(["git"] + list(args), cwd=ROOT, input=input_bytes, capture_output=True)
    if check and p.returncode != 0:
        sys.exit("git %s 失败: %s" % (" ".join(args), p.stderr.decode("utf-8", "replace")))
    return p.stdout


def has(sha):
    return subprocess.run(["git", "cat-file", "-e", sha], cwd=ROOT,
                          capture_output=True).returncode == 0


def cred_token():
    p = subprocess.run(["git", "credential", "fill"], cwd=ROOT,
                       input=b"protocol=https\nhost=github.com\n\n", capture_output=True,
                       env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("password="):
            return line[len("password="):]
    sys.exit("未取到 GitHub 凭据（git credential fill 无 password）")


TOKEN = cred_token()
STAT = {"tree": 0, "blob": 0, "commit": 0, "skip": 0}


def api(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "replace")[:300]}


def fetch_raw(path):
    """取二进制内容（blob 的 raw 端点）。"""
    req = urllib.request.Request(API + path)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github.raw")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def write_blob(sha):
    """下载并写入一个 blob，返回是否成功。"""
    if has(sha):
        STAT["skip"] += 1
        return
    if DRY_RUN:
        print("      [缺] blob %s（dry-run 不下载）" % sha[:12])
        return
    data = fetch_raw("/repos/%s/%s/git/blobs/%s" % (OWNER, REPO, sha))
    got = git("hash-object", "-t", "blob", "-w", "--stdin", input_bytes=data).decode().strip()
    if got != sha:
        sys.exit("blob 哈希不符：期望 %s，实得 %s" % (sha, got))
    STAT["blob"] += 1


def write_tree(sha, depth=0):
    """递归补齐一棵 tree（先确保子对象都在，再用 mktree 写自己）。"""
    if has(sha):
        STAT["skip"] += 1
        return
    st, d = api("GET", "/repos/%s/%s/git/trees/%s" % (OWNER, REPO, sha))
    if st != 200:
        sys.exit("读取 tree 失败 %s: %s" % (st, d))
    if d.get("truncated"):
        sys.exit("tree 被截断（仓库过大），本脚本不支持，请改用 git fetch")
    entries = d.get("tree", [])
    for e in entries:
        if e["type"] == "tree":
            write_tree(e["sha"], depth + 1)
        elif e["type"] == "blob":
            write_blob(e["sha"])
    if DRY_RUN:
        print("      [缺] tree %s（%d 项）" % (sha[:12], len(entries)))
        return
    # mktree -z：用 NUL 分隔，避免中文文件名与转义规则互相干扰
    buf = b"".join(("%s %s %s\t%s" % (e["mode"], e["type"], e["sha"], e["path"]))
                   .encode("utf-8") + b"\0" for e in entries)
    got = git("mktree", "-z", input_bytes=buf).decode().strip()
    if got != sha:
        sys.exit("tree 哈希不符：期望 %s，实得 %s" % (sha, got))
    STAT["tree"] += 1


def epoch(iso):
    import calendar
    import time
    return calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))


def commit_hash(obj):
    """在进程内计算提交对象的 SHA-1（等价 git hash-object，但快两个数量级）。"""
    return hashlib.sha1(b"commit %d\x00" % len(obj) + obj).hexdigest()


def commit_verification(sha):
    """取提交的签名校验信息（网页端提交会被 GitHub 用 GPG 签名）。"""
    st, d = api("GET", "/repos/%s/%s/commits/%s" % (OWNER, REPO, sha))
    if st != 200:
        return {}
    return d.get("commit", {}).get("verification", {}) or {}


def write_commit(d):
    """按 API 元数据重建提交对象，枚举时区/尾换行命中目标 SHA。"""
    target = d["sha"]
    if has(target):
        STAT["skip"] += 1
        return

    # 网页端提交（Edit file / Merge）会被 GitHub 用 web-flow 密钥签名，对象里有 gpgsig 头。
    # API 的 verification.payload 是「重新序列化」的文本、signature 也不保证与对象内一字不差，
    # 拼不回原字节 —— 这种提交只能靠 git fetch 取。先明确报出来，别让用户看到一句莫名的失败。
    if commit_verification(target).get("signature"):
        sys.exit(
            "中止：提交 %s 带 GitHub 签名（网页端改文件产生的提交），无法在本地逐字节重建。\n"
            "     对象里含 gpgsig 头，而 API 只提供重新序列化过的 payload，拼不回原始字节。\n"
            "     解决：在能访问 github.com 的网络里执行一次 `git fetch origin` 即可补齐。\n"
            "     （本脚本只能补「普通未签名提交」，例如自己用 API 推上去的那些。）" % target[:12])

    tree = d["tree"]["sha"]
    parents = [p["sha"] for p in d.get("parents", [])]
    ae, ce = epoch(d["author"]["date"]), epoch(d["committer"]["date"])
    an, am = d["author"]["name"], d["author"]["email"]
    cn, cm = d["committer"]["name"], d["committer"]["email"]
    msg = d["message"]

    if DRY_RUN:
        print("      [缺] commit %s  %s" % (target[:12], msg.splitlines()[0][:50]))
        return

    # 递归补齐 tree
    write_tree(tree)

    head = "tree %s\n" % tree
    for p in parents:
        head += "parent %s\n" % p
    hit = None
    for tza, tzc, tail in itertools.product(TZS, TZS, ("", "\n", "\n\n")):
        obj = (head
               + "author %s <%s> %d %s\n" % (an, am, ae, tza)
               + "committer %s <%s> %d %s\n" % (cn, cm, ce, tzc)
               + "\n" + msg + tail).encode("utf-8")
        if commit_hash(obj) == target:
            hit = obj
            break
    if hit is None:
        sys.exit("无法重建提交对象 %s（时区/尾换行枚举都未命中）——需要人工介入" % target)
    got = git("hash-object", "-t", "commit", "-w", "--stdin", input_bytes=hit).decode().strip()
    if got != target:
        sys.exit("提交对象写入后哈希不符：期望 %s，实得 %s" % (target, got))
    STAT["commit"] += 1
    print("      [补] commit %s  %s" % (target[:12], msg.splitlines()[0][:50]))


def main():
    st, ref = api("GET", "/repos/%s/%s/git/ref/%s" % (OWNER, REPO, REF))
    if st == 404:
        st, ref = api("GET", "/repos/%s/%s/git/ref/heads/%s" % (OWNER, REPO, REF))
    if st == 404:
        st, ref = api("GET", "/repos/%s/%s/git/ref/tags/%s" % (OWNER, REPO, REF))
    if st != 200:
        sys.exit("读取远端 ref 失败 %s: %s" % (st, ref))
    tip = ref["object"]["sha"]
    print("远端 %-10s: %s" % (REF, tip))
    if not has(tip):
        print("  本地缺这个提交对象，开始往下找……")

    # 1) 收集缺失提交：沿父链向下走，遇到「对象在本地且整条祖先链完整」的提交才剪枝。
    #    只判断「对象在不在」是不够的 —— 之前用 API 推过的提交就在本地，
    #    但它指向的网页端父提交可能仍然缺失，必须继续往下走。
    missing = []
    visited = set()
    queue = [tip]
    while queue:
        sha = queue.pop(0)
        if sha in visited:
            continue
        visited.add(sha)
        st, d = api("GET", "/repos/%s/%s/git/commits/%s" % (OWNER, REPO, sha))
        if st != 200:
            sys.exit("读取远端提交失败 %s: %s" % (st, d))
        if has(sha):
            ok = subprocess.run(["git", "rev-list", "--count", sha], cwd=ROOT, capture_output=True)
            if ok.returncode == 0:
                continue                      # 祖先链完整，剪枝
        else:
            missing.append(d)
        for p in d.get("parents", []):
            queue.append(p["sha"])
        if len(visited) > 2000:
            sys.exit("遍历提交超过 2000 个，请改用 git fetch")
    if not missing:
        print("本地对象完整，无需补齐。")
        return
    print("发现 %d 个本地缺失的提交：" % len(missing))
    for d in reversed(missing):
        print("  %s  %s  %s" % (d["sha"][:12], d["author"]["date"],
                                d["message"].splitlines()[0][:50]))

    # 2) 由老到新重建（父对象必须先就位）
    print("\n开始补齐%s……" % ("（dry-run，不写入）" if DRY_RUN else ""))
    for d in reversed(missing):
        write_commit(d)

    print("\n对象统计：新增 commit %d / tree %d / blob %d，已存在跳过 %d"
          % (STAT["commit"], STAT["tree"], STAT["blob"], STAT["skip"]))
    if DRY_RUN:
        return

    # 3) 校验遍历
    p = subprocess.run(["git", "log", "--oneline", "-%d" % (len(missing) + 3)], cwd=ROOT,
                       capture_output=True)
    if p.returncode != 0:
        sys.exit("补齐后 git log 仍失败：%s" % p.stderr.decode("utf-8", "replace"))
    print("git log 已可正常遍历：")
    for line in p.stdout.decode("utf-8", "replace").strip().splitlines():
        print("  " + line)
    print("\n完成。本地 %s 现在指向 %s（工作区未改动，如有需要可 git merge / reset --hard 到该提交）"
          % (REF, tip[:12]))


if __name__ == "__main__":
    main()
