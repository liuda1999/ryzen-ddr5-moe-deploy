# -*- coding: utf-8 -*-
"""推送后审计：逐文件核对远端仓库与本地 HEAD 是否完全一致。

为什么需要这个脚本：
    本项目在受限网络下走 Git Data API 推送（见 push_via_api.py），本地 ref 不跟随
    远端，`git status` / `git log` 都看不出「远端到底推全了没有」。而提交频繁时，
    最容易出的事故是：只推了部分 blob、树和本地不一致、tag/Release 落空、
    或者远端残留了本地已删的文件。

检查项（全部只读，不写远端）：
    1. 远端 main 的提交号、树号，与本地 HEAD 是否一致（字节级）
    2. 远端树 vs 本地 `git ls-tree -r -l HEAD` 逐文件比对：路径、mode、blob、大小
    3. 差异分类：远端多 / 远端缺 / 内容不同 / 大小不同
    4. 远端最近提交历史、作者、时间（确认多次推送没有把历史推乱）
    5. 远端 tag 与 Release：tag 是否存在、指向的树是否正确、附件大小是否对得上
    6. 敏感文件是否误入库（api-key、*.gguf、日志、临时编译目录）

用法：
    python audit_remote.py               # 完整审计
    python audit_remote.py --quick       # 跳过 Release 附件明细
"""
import argparse
import base64
import hashlib
import http.client
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

OWNER = "liuda1999"
REPO = "ryzen-ddr5-moe-deploy"
BRANCH = "main"
API = "https://api.github.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 不该入库的东西：密钥、模型、打包产物、运行日志、临时编译目录
SENSITIVE = ("api-key", ".env", ".gguf", ".log", ".zip", ".7z", ".dmp")
SENSITIVE_DIRS = ("logs", "_build", "build-cuda", "__pycache__", ".venv")


def is_sensitive(path):
    """按路径分量判断，避免 logs/ 误伤 llama.cpp 里的 dialogs/ 目录。"""
    low = path.lower()
    if low.endswith(SENSITIVE):
        return True
    parts = low.split("/")
    for d in SENSITIVE_DIRS:
        if any(seg == d or seg.startswith(d) for seg in parts[:-1]):
            return True
    return False


def git(*args):
    p = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True)
    if p.returncode != 0:
        sys.exit("git %s 失败: %s" % (" ".join(args), p.stderr.decode("utf-8", "replace")))
    return p.stdout.decode("utf-8", "replace")


def cred_token():
    p = subprocess.run(["git", "credential", "fill"], cwd=ROOT,
                       input=b"protocol=https\nhost=github.com\n\n", capture_output=True,
                       env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("password="):
            return line[len("password="):]
    sys.exit("未取到 GitHub 凭据（git credential fill 无 password）")


TOKEN = cred_token()


def api(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    last = None
    for attempt in range(3):
        req = urllib.request.Request(API + path, data=data, method=method)
        req.add_header("Authorization", "Bearer " + TOKEN)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                body = r.read().decode("utf-8", "replace")
                return r.status, (json.loads(body) if body else {})
        except urllib.error.HTTPError as e:
            return e.code, {"error": e.read().decode("utf-8", "replace")[:400]}
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
            last = e
            if attempt < 2:
                print("  [重试 %d/2] %s 失败（%s），稍后重来" % (attempt + 1, path.split("?")[0], e))
    raise SystemExit("请求失败（已重试 2 次）：%s -> %s" % (path, last))


def must(method, path):
    code, body = api(method, path)
    if code != 200:
        sys.exit("接口返回 %s：%s\n%s" % (code, path, body.get("error", body)))
    return body


def hsize(n):
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return "%.1f TB" % n


def local_map():
    """path -> (mode, sha, size)；-l 给出 blob 大小，submodule 无 size。"""
    out = {}
    for line in git("ls-tree", "-r", "-l", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        parts = meta.split()
        mode, _typ, sha = parts[0], parts[1], parts[2]
        size = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
        out[path] = (mode, sha, size)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="跳过 Release 附件明细")
    args = ap.parse_args()

    fails = []
    warns = []

    print("=" * 78)
    print("推送审计  %s/%s  branch=%s" % (OWNER, REPO, BRANCH))
    print("=" * 78)

    # ---------- 1. 远端 main 的提交与树 ----------
    local_head = git("rev-parse", "HEAD").strip()
    local_tree = git("rev-parse", "HEAD^{tree}").strip()
    local_msg = git("log", "-1", "--pretty=%B").strip()
    local_when = git("log", "-1", "--pretty=%cI").strip()
    local_subj = git("log", "-1", "--pretty=%s").strip()

    ref = must("GET", "/repos/%s/%s/git/ref/heads/%s" % (OWNER, REPO, BRANCH))
    remote_sha = ref["object"]["sha"]
    rcommit = must("GET", "/repos/%s/%s/git/commits/%s" % (OWNER, REPO, remote_sha))
    remote_tree = rcommit["tree"]["sha"]
    remote_msg = (rcommit.get("message") or "").strip()

    print("\n[1] 远端 main 提交")
    print("  远端提交      : %s" % remote_sha)
    print("  远端 tree     : %s" % remote_tree)
    print("  本地 HEAD     : %s" % local_head)
    print("  本地 tree     : %s" % local_tree)
    print("  远端提交信息  : %s" % (remote_msg.splitlines() or ["(空)"])[0][:60])
    print("  远端提交时间  : %s" % rcommit["committer"]["date"])
    print("  本地提交时间  : %s" % local_when)

    predicted = ""
    if os.path.exists(os.path.join(ROOT, ".git", "info", "PUSHED_HEAD")):
        predicted = open(os.path.join(ROOT, ".git", "info", "PUSHED_HEAD")).read().strip()

    if remote_tree == local_tree:
        print("  结论          : [OK] 树一致（远端内容 == 本地 HEAD 内容）")
    else:
        print("  结论          : [!!] 树不一致")
        fails.append("远端 tree %s != 本地 tree %s" % (remote_tree, local_tree))

    if predicted and predicted != remote_sha:
        warns.append("PUSHED_HEAD 记录 %s，与远端当前 %s 不同（可能之后又有提交）"
                     % (predicted[:12], remote_sha[:12]))
        print("  记录核对      : 本地记录的上次推送 %s（远端已前进）" % predicted[:12])
    print("  提交信息一致  : %s" % ("是" if remote_msg == local_msg.strip() else "否"))
    if remote_msg != local_msg.strip():
        fails.append("远端提交信息与本地 HEAD 不一致")

    # ---------- 2. 逐文件比对 ----------
    print("\n[2] 逐文件比对（以树为准，不做增量推断）")
    lmap = local_map()
    rtree = must("GET", "/repos/%s/%s/git/trees/%s?recursive=1" % (OWNER, REPO, remote_tree))
    if rtree.get("truncated"):
        fails.append("远端树被截断（truncated=true），比对不完整")
        print("  [!!] 远端树返回 truncated=true，文件过多无法一次取全")
    rmap = {}
    for e in rtree["tree"]:
        if e["type"] != "blob":
            continue
        rmap[e["path"]] = (e["mode"], e["sha"], e.get("size"))

    only_remote = sorted(set(rmap) - set(lmap))
    only_local = sorted(set(lmap) - set(rmap))
    diff_sha = sorted(p for p in set(lmap) & set(rmap) if lmap[p][1] != rmap[p][1])
    diff_size = sorted(p for p in set(lmap) & set(rmap)
                       if lmap[p][2] is not None and rmap[p][2] is not None
                       and lmap[p][2] != rmap[p][2])
    diff_mode = sorted(p for p in set(lmap) & set(rmap) if lmap[p][0] != rmap[p][0])

    print("  远端文件数    : %d" % len(rmap))
    print("  本地文件数    : %d" % len(lmap))
    print("  完全一致      : %d" % (len(set(lmap) & set(rmap)) - len(diff_sha)))
    print("  仅远端有      : %d" % len(only_remote))
    print("  仅本地有      : %d" % len(only_local))
    print("  内容不同      : %d" % len(diff_sha))
    print("  大小不同      : %d" % len(diff_size))
    print("  mode 不同     : %d" % len(diff_mode))

    for tag, items in (("仅远端有（本地已删但没推删）", only_remote),
                       ("仅本地有（没推上去）", only_local),
                       ("内容不同（blob 哈希不一致）", diff_sha),
                       ("大小不同", diff_size)):
        if items:
            fails.append("%s：%d 个文件" % (tag, len(items)))
            print("  [!!] %s：" % tag)
            for p in items[:12]:
                print("        %s  local=%s remote=%s"
                      % (p, hsize(lmap.get(p, (None, None, None))[2]),
                         hsize(rmap.get(p, (None, None, None))[2])))
            if len(items) > 12:
                print("        ... 另有 %d 个" % (len(items) - 12))
    if not (only_remote or only_local or diff_sha or diff_size):
        print("  [OK] 全部文件路径 / blob / 大小一一对应")

    # 总字节数（便于肉眼核对量级）
    lb = sum(v[2] or 0 for v in lmap.values())
    rb = sum(v[2] or 0 for v in rmap.values())
    print("  总字节        : 本地 %s / 远端 %s" % (hsize(lb), hsize(rb)))

    # ---------- 2b. 抽样取回真实字节 ----------
    # 必须走 blobs 接口：contents 接口会把非 UTF-8 文本（本项目的 GBK bat）
    # 转成 UTF-8 再返回，字节数和哈希都对不上，会误报「推送内容不一致」。
    print("\n[2b] 抽样取回 blob，校验远端存储的真实字节")
    sample = [p for p in ("启动大模型_StartModel.bat", "README.md",
                          "_维护脚本/gen_toggle.py") if p in rmap]
    # 再抽一个 1 MB 以内的二进制（dll 最大 8 MB，走接口太慢，取小的即可证明二进制存取正常）
    bins = sorted(((v[2] or 0, p) for p, v in rmap.items()
                   if p.lower().endswith((".dll", ".exe")) and (v[2] or 0) < 1 << 20))
    if bins:
        sample.append(bins[0][1])
    for p in sample:
        blob = must("GET", "/repos/%s/%s/git/blobs/%s" % (OWNER, REPO, rmap[p][1]))
        raw = base64.b64decode(blob["content"])
        h = hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()
        ok = (h == rmap[p][1] and len(raw) == (rmap[p][2] or len(raw)))
        print("  [%s] %-26s %8s  sha1=%s" % ("OK" if ok else "!!", p, hsize(len(raw)), h[:10]))
        if not ok:
            fails.append("抽样 blob %s 取回后哈希不符" % p)

    # ---------- 3. 敏感文件 ----------
    print("\n[3] 敏感文件 / 不该入库的产物")
    bad = [p for p in rmap if is_sensitive(p)]
    big = sorted(((v[2] or 0, p) for p, v in rmap.items()), reverse=True)[:3]
    if bad:
        print("  [!!] 命中 %d 个：" % len(bad))
        for p in bad[:10]:
            print("        %s" % p)
        fails.append("远端含疑似不该入库的文件 %d 个" % len(bad))
    else:
        print("  [OK] 未发现 api-key / 模型 / 压缩包 / 日志 / 临时编译目录")
    print("  最大三个文件  :")
    for sz, p in big:
        print("        %s  %s" % (hsize(sz), p))
    over = [p for p, v in rmap.items() if (v[2] or 0) >= 50 * 1024 * 1024]
    if over:
        warns.append("有 %d 个文件 >= 50 MB（GitHub 上限 100 MB，克隆会变慢）" % len(over))

    # ---------- 4. 远端提交历史 ----------
    print("\n[4] 远端最近提交（核对多次推送是否把历史推乱）")
    hist = []
    sha = remote_sha
    for _ in range(20):
        c = must("GET", "/repos/%s/%s/git/commits/%s" % (OWNER, REPO, sha))
        hist.append(c)
        parents = c.get("parents") or []
        if len(parents) > 1:
            warns.append("远端出现合并提交 %s（父节点 %d 个）" % (sha[:12], len(parents)))
        if not parents:
            break
        sha = parents[0]["sha"]
    for c in hist[:8]:
        print("  %s  %s  %s" % (c["sha"][:8], c["committer"]["date"][:19],
                                (c.get("message") or "").splitlines()[0][:52]))
    if any(len(c.get("parents") or []) > 1 for c in hist):
        print("  [!!] 历史中存在合并提交")

    print("\n[4b] 本地 / 远端历史谱系")
    have = [c["sha"] for c in hist
            if subprocess.run(["git", "cat-file", "-e", c["sha"] + "^{commit}"],
                              cwd=ROOT, capture_output=True).returncode == 0]
    print("  远端历史抽查  : %d 个提交，本地存在 %d 个" % (len(hist), len(have)))
    if not have:
        print("  [!!] 两条历史没有公共提交（本地 ref 从未跟随过远端）")
        print("       影响：远端内容可以逐文件对上，但 `git push` 会以 non-fast-forward")
        print("       被拒；必须继续用 push_via_api.py，或显式 --force 覆盖远端历史。")
        warns.append("本地与远端历史无公共提交：常规 git push 会被拒，只能走 API 推送")
    else:
        print("  公共提交      : %s" % ", ".join(s[:8] for s in have[-4:]))
    missing = [c["sha"] for c in hist if c["sha"] not in have]
    if missing:
        warns.append("本地对象库缺 %d 个远端提交（如 %s）：本地无法遍历完整远端历史，"
                     "git gc 还会清掉不可达的远端提交副本；核对请以本脚本为准"
                     % (len(missing), ", ".join(s[:8] for s in missing[:3])))

    # ---------- 5. tag / Release ----------
    print("\n[5] 分支 / tag / Release")
    repo_info = must("GET", "/repos/%s/%s" % (OWNER, REPO))
    print("  默认分支      : %s" % repo_info.get("default_branch"))
    if repo_info.get("default_branch") != BRANCH:
        fails.append("默认分支是 %s，不是 %s" % (repo_info.get("default_branch"), BRANCH))
    brs = must("GET", "/repos/%s/%s/branches?per_page=100" % (OWNER, REPO))
    bnames = [b["name"] for b in brs]
    print("  远端分支      : %s" % ", ".join(bnames))
    extra = [b for b in bnames if b != BRANCH]
    if extra:
        warns.append("远端存在非主线分支：%s" % ", ".join(extra))

    tags = must("GET", "/repos/%s/%s/git/refs/tags" % (OWNER, REPO))
    tnames = sorted(t["ref"].replace("refs/tags/", "") for t in tags)
    print("  远端 tag      : %s" % (", ".join(tnames) or "(无)"))
    local_tags = sorted(git("tag", "-l").split())
    print("  本地 tag      : %s" % (", ".join(local_tags) or "(无)"))
    miss_tag = [t for t in local_tags if t not in tnames]
    if miss_tag:
        warns.append("本地 tag 未推到远端：%s" % ", ".join(miss_tag))

    for t in tags:
        name = t["ref"].replace("refs/tags/", "")
        sha = t["object"]["sha"]
        obj = must("GET", "/repos/%s/%s/git/commits/%s" % (OWNER, REPO, sha))
        same = "树一致" if obj["tree"]["sha"] == local_tree else "树=%s" % obj["tree"]["sha"][:8]
        print("    %-8s -> %s  %s" % (name, sha[:8], same))

    rels = must("GET", "/repos/%s/%s/releases?per_page=20" % (OWNER, REPO))
    print("  Release 数    : %d" % len(rels))
    for r in rels[:5]:
        assets = r.get("assets") or []
        flag = "草稿" if r.get("draft") else ("预发布" if r.get("prerelease") else "已发布")
        print("    %-8s %-4s tag=%s  附件 %d 个"
              % (r.get("tag_name"), flag, r.get("tag_name"), len(assets)))
        for a in assets:
            print("        %s  %s  state=%s downloads=%d"
                  % (a["name"], hsize(a["size"]), a.get("state"), a.get("download_count", 0)))
    if rels and rels[0].get("draft"):
        fails.append("最新 Release 仍是草稿状态，未发布")

    # 附件逐字节对账：大小相同不代表上传完整，能取到 digest 就比 sha256
    rel_dir = os.path.join(os.path.dirname(ROOT), "llm-cpp-release")
    for r in rels[:3]:
        tag = (r.get("tag_name") or "").lstrip("v")
        for a in r.get("assets") or []:
            cand = sorted(p for p in os.listdir(rel_dir)
                          if tag and tag in p and p.endswith(".zip")) \
                if os.path.isdir(rel_dir) else []
            for p in cand:
                lp = os.path.join(rel_dir, p)
                ls = os.path.getsize(lp)
                ok = (ls == a["size"])
                print("        [%s] 本地 %s %s vs 附件 %s"
                      % ("OK" if ok else "!!", p, hsize(ls), hsize(a["size"])))
                if not ok:
                    fails.append("Release 附件 %s 大小与本地包不符" % a["name"])
                    continue
                detail = must("GET", "/repos/%s/%s/releases/assets/%d"
                              % (OWNER, REPO, a["id"]))
                dig = detail.get("digest")
                if dig and dig.startswith("sha256:"):
                    h = hashlib.sha256()
                    with open(lp, "rb") as f:
                        for chunk in iter(lambda: f.read(1 << 20), b""):
                            h.update(chunk)
                    same = h.hexdigest() == dig.split(":", 1)[1]
                    print("        [%s] sha256 %s" % ("OK" if same else "!!", h.hexdigest()[:16]))
                    if not same:
                        fails.append("附件 %s sha256 与本地包不符（上传损坏？）" % a["name"])
                else:
                    print("        [--] 接口未返回 digest，仅比对了大小")

    # ---------- 6. 结论 ----------
    print("\n" + "=" * 78)
    if fails:
        print("结论：未通过，%d 项问题" % len(fails))
        for f in fails:
            print("  [!!] %s" % f)
    else:
        print("结论：通过 —— 远端 main 与本地 HEAD 内容完全一致，tag/Release 无异常")
    if warns:
        print("提示（不阻断）：")
        for w in warns:
            print("  - %s" % w)
    print("=" * 78)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
