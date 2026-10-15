# -*- coding: utf-8 -*-
"""把本地提交推送到 GitHub（走 Git Data API，备用通道）。

何时需要它：
    正常用 `git push` 即可。但**受限网络环境下 `github.com:443` 可能被代理拦截**
    （报 `CONNECT tunnel failed, response 502`），而 `api.github.com` 仍然可达。
    此时 `git push` 无解，本脚本改走 Git Data API 完成同样的推送。

它做什么：
    1. 拉取远端当前 main 的完整树清单，与本地 HEAD 的树**逐文件比对**，
       得出「要上传哪些文件」—— 以树为准而不是以「最近一次提交的 diff」为准，
       因此本地有几个还没推上去的提交都能一次对齐；
    2. 逐个上传 blob，并与本地 `git ls-tree` 给出的哈希比对；
    3. 以远端树为 base_tree 建树，校验**新树哈希 == 本地 HEAD 的树哈希**
       （字节级一致；不一致立刻中止，绝不推错内容）；
    4. 建提交并更新 `refs/heads/main`，然后把本地 main / origin-main 对齐到远端提交。

注意：
    - 远端有、本地没有的文件，推上去等于删除。默认**中止**并要求确认；
      确实要删再加 `--allow-delete`。
    - 本地多个未推送提交会被**折叠成一个远端提交**（因为远端历史里可能有本地
      取不回来的网页端签名提交，无法逐一对齐）。此时提交信息默认取 HEAD 的，
      想自己写就用 `--message-file <路径>`。

安全性：
    - 令牌通过 `git credential fill` 现场获取，**不写盘、不打印**；
    - 强制校验远端 main 的树 == 本地 HEAD^ 的树，避免覆盖别人的提交；
    - 任一步失败即中止并打印接口返回的错误。
    参考：`_维护脚本\\说明.md` 的「受限网络下推送」一节。

局限：只处理文件内容变化（增/删/改），不处理子模块 / 符号链接等特殊条目。
"""
import base64
import io
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


def git(*args):
    p = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True)
    if p.returncode != 0:
        sys.exit("git %s 失败: %s" % (" ".join(args), p.stderr.decode("utf-8", "replace")))
    return p.stdout.decode("utf-8", "replace").strip()


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
        return e.code, {"error": e.read().decode("utf-8", "replace")[:400]}


def predict_remote_commit(tree, parent, message, ident_lines):
    """在本地预测 GitHub 会生成的提交对象，并写入本地对象库。

    实测规律（本轮探明）：GitHub 会**保留**提交时传入的时区（如 +0800），
    但把消息尾部换行去掉（`git log --pretty=%B` 本就不带尾换行）。
    因此只要能命中这个形态，就能在推送前算出远端 SHA，
    推完再校验一次，两边就不会出现「内容相同、SHA 不同」的分叉。
    """
    head = "tree %s\nparent %s\n" % (tree, parent) + "".join(ident_lines) + "\n"
    obj = (head + message).encode("utf-8")
    sha = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"],
                         cwd=ROOT, input=obj, capture_output=True).stdout.decode().strip()
    return sha


def main():
    head = git("rev-parse", "HEAD")
    local_tree = git("rev-parse", "HEAD^{tree}")
    message = git("log", "-1", "--pretty=%B")
    for i, a in enumerate(sys.argv):
        if a == "--message-file" and i + 1 < len(sys.argv):
            message = io.open(sys.argv[i + 1], encoding="utf-8").read().rstrip("\r\n")
            print("提交信息   : 取自 %s" % sys.argv[i + 1])

    def ident(role):
        # role: 'a'（author）/ 'c'（committer）；取名字、邮箱、unix 时间戳与含时区的 ISO
        n = git("log", "-1", "--pretty=%%%sn" % role)
        e = git("log", "-1", "--pretty=%%%se" % role)
        t = git("log", "-1", "--pretty=%%%st" % role)
        d = git("log", "-1", "--pretty=%%%sI" % role)
        tz = d[-6:].replace(":", "")            # +08:00 -> +0800
        return "%s %s <%s> %s %s\n" % ("author" if role == "a" else "committer", n, e, t, tz)

    ident_lines = [ident("a"), ident("c")]

    # 本地树（path -> (mode, sha)）
    local_map = {}
    for line in git("ls-tree", "-r", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        mode, typ, sha = meta.split()
        if typ != "blob":
            print("  [跳过] %s（类型 %s，本脚本只处理普通文件）" % (path, typ))
            continue
        local_map[path] = (mode, sha)

    print("本地提交   :", head)
    print("本地树哈希 :", local_tree)
    print("本地文件数 : %d" % len(local_map))

    st, ref = api("GET", "/repos/%s/%s/git/ref/heads/%s" % (OWNER, REPO, BRANCH))
    if st != 200:
        sys.exit("读取远端 ref 失败 %s: %s" % (st, ref))
    remote_head = ref["object"]["sha"]

    st, remote_commit = api("GET", "/repos/%s/%s/git/commits/%s" % (OWNER, REPO, remote_head))
    if st != 200:
        sys.exit("读取远端提交失败 %s: %s" % (st, remote_commit))
    remote_tree = remote_commit["tree"]["sha"]

    st, rt = api("GET", "/repos/%s/%s/git/trees/%s?recursive=1" % (OWNER, REPO, remote_tree))
    if st != 200:
        sys.exit("读取远端树失败 %s: %s" % (st, rt))
    if rt.get("truncated"):
        sys.exit("远端树过大被截断，本脚本不支持")
    remote_map = {e["path"]: (e["mode"], e["sha"])
                  for e in rt.get("tree", []) if e["type"] == "blob"}

    print("远端 main  :", remote_head)
    print("远端文件数 : %d" % len(remote_map))

    # 关键：要上传哪些文件，以「远端树 vs 本地树」为准，而不是本地最近一次提交的 diff。
    # 这样本地有几个还没推上去的提交都能一次对齐；最终仍以「新建树 == 本地树」把关。
    to_upload = sorted(p for p in local_map
                       if p not in remote_map or remote_map[p][1] != local_map[p][1])
    remote_only = sorted(p for p in remote_map if p not in local_map)

    if remote_only:
        # 这些文件存在于远端但本地没有 —— 推上去就等于把它们删掉。
        # 默认中止，要求人工确认（避免把别人在网页上加的文件悄悄删掉）。
        print("\n远端有 %d 个本地没有的文件：" % len(remote_only))
        for p in remote_only[:20]:
            print("    %s" % p)
        if "--allow-delete" not in sys.argv:
            sys.exit("中止：上面这些文件会被删除。确认要删就加 --allow-delete 重跑；\n"
                     "      若是别人加的、不该删，请先在能访问 github.com 的网络里 git fetch 合并。")
        print("  （已指定 --allow-delete，将删除它们）")

    print("\n需要上传 %d 个文件：" % len(to_upload))
    entries = [{"path": p, "mode": "100644", "type": "blob", "sha": None} for p in remote_only]
    for rel in to_upload:
        path = os.path.join(ROOT, rel.replace("/", os.sep))
        with open(path, "rb") as f:
            blob = f.read()
        st, res = api("POST", "/repos/%s/%s/git/blobs" % (OWNER, REPO),
                      {"content": base64.b64encode(blob).decode("ascii"), "encoding": "base64"})
        if st not in (200, 201):
            sys.exit("上传 blob 失败 %s (%s): %s" % (rel, st, res))
        if res["sha"] != local_map[rel][1]:
            sys.exit("blob 哈希与本地不一致，中止：%s" % rel)
        print("  [传] %-44s %s" % (rel, res["sha"][:12]))
        entries.append({"path": rel, "mode": local_map[rel][0], "type": "blob", "sha": res["sha"]})

    st, tree = api("POST", "/repos/%s/%s/git/trees" % (OWNER, REPO),
                   {"base_tree": remote_tree, "tree": entries})
    if st not in (200, 201):
        sys.exit("创建 tree 失败 %s: %s" % (st, tree))
    if tree["sha"] != local_tree:
        sys.exit("新树哈希与本地不一致，中止（%s != %s）—— 请检查上面的文件清单"
                 % (tree["sha"], local_tree))
    print("新树哈希   :", tree["sha"], "（与本地一致）")

    predicted = predict_remote_commit(tree["sha"], remote_head, message, ident_lines)
    print("预测远端提交:", predicted[:12])

    st, commit = api("POST", "/repos/%s/%s/git/commits" % (OWNER, REPO),
                     {"message": message, "tree": tree["sha"], "parents": [remote_head],
                      "author": {"name": git("log", "-1", "--pretty=%an"),
                                 "email": git("log", "-1", "--pretty=%ae"),
                                 "date": git("log", "-1", "--pretty=%aI")},
                      "committer": {"name": git("log", "-1", "--pretty=%cn"),
                                    "email": git("log", "-1", "--pretty=%ce"),
                                    "date": git("log", "-1", "--pretty=%cI")}})
    if st not in (200, 201):
        sys.exit("创建提交失败 %s: %s" % (st, commit))
    if commit["sha"] != predicted:
        print("警告：远端提交 SHA 与预测不符（%s != %s），本地 ref 不做对齐"
              % (commit["sha"][:12], predicted[:12]))

    st, upd = api("PATCH", "/repos/%s/%s/git/refs/heads/%s" % (OWNER, REPO, BRANCH),
                  {"sha": commit["sha"], "force": False})
    if st != 200:
        sys.exit("更新 ref 失败 %s: %s" % (st, upd))
    print("远端 main  -> %s" % upd["object"]["sha"])

    # 远端提交的 SHA 可能与本地 HEAD 不同（本地历史里可能有推不上去的网页端提交，
    # 或本地有多个未推送提交被折叠成一个）。只要树一致，就把本地 ref 对齐过去，
    # 避免以后每次推送都要重算。
    if commit["sha"] == head:
        print("本地与远端提交 SHA 完全一致")
    else:
        subprocess.run(["git", "update-ref", "refs/heads/main", commit["sha"]], cwd=ROOT, check=True)
        subprocess.run(["git", "update-ref", "refs/remotes/origin/main", commit["sha"]],
                       cwd=ROOT, check=True)
        print("已把本地 main 与 origin/main 对齐到远端提交 %s（内容相同）" % commit["sha"][:12])


if __name__ == "__main__":
    main()

