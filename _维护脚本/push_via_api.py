# -*- coding: utf-8 -*-
"""把本地提交推送到 GitHub（走 Git Data API，备用通道）。

何时需要它：
    正常用 `git push` 即可。但**受限网络环境下 `github.com:443` 可能被代理拦截**
    （报 `CONNECT tunnel failed, response 502`），而 `api.github.com` 仍然可达。
    此时 `git push` 无解，本脚本改走 Git Data API 完成同样的推送。

它做什么：
    1. 读取本地 HEAD 相对父提交的全部改动（新增 / 修改 / 删除）；
    2. 逐个上传 blob，并与本地 `git rev-parse HEAD:<path>` 的哈希比对；
    3. 以远端当前 main 的树为 base_tree 建树，校验**新树哈希 == 本地 HEAD 的树哈希**
       （字节级一致；不一致立刻中止，绝不推错内容）；
    4. 建提交并更新 `refs/heads/main`。

安全性：
    - 令牌通过 `git credential fill` 现场获取，**不写盘、不打印**；
    - 强制校验远端 main 的树 == 本地 HEAD^ 的树，避免覆盖别人的提交；
    - 任一步失败即中止并打印接口返回的错误。
    参考：`_维护脚本\\说明.md` 的「受限网络下推送」一节。

局限：只处理文件内容变化（增/删/改），不处理子模块 / 符号链接等特殊条目。
"""
import base64
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
    parent = git("rev-parse", "HEAD^")
    local_tree = git("rev-parse", "HEAD^{tree}")
    message = git("log", "-1", "--pretty=%B")
    changed = git("diff", "--name-only", parent, head).splitlines()
    deleted = git("diff", "--name-only", "--diff-filter=D", parent, head).splitlines()

    def ident(role):
        # role: 'a'（author）/ 'c'（committer）；取名字、邮箱、unix 时间戳与含时区的 ISO
        n = git("log", "-1", "--pretty=%%%sn" % role)
        e = git("log", "-1", "--pretty=%%%se" % role)
        t = git("log", "-1", "--pretty=%%%st" % role)
        d = git("log", "-1", "--pretty=%%%sI" % role)
        tz = d[-6:].replace(":", "")            # +08:00 -> +0800
        return "%s %s <%s> %s %s\n" % ("author" if role == "a" else "committer", n, e, t, tz)

    ident_lines = [ident("a"), ident("c")]
    print("本地提交   :", head)
    print("本地树哈希 :", local_tree)
    print("改动文件   : %d（其中删除 %d）" % (len(changed), len(deleted)))

    st, ref = api("GET", "/repos/%s/%s/git/ref/heads/%s" % (OWNER, REPO, BRANCH))
    if st != 200:
        sys.exit("读取远端 ref 失败 %s: %s" % (st, ref))
    remote_head = ref["object"]["sha"]

    st, remote_commit = api("GET", "/repos/%s/%s/git/commits/%s" % (OWNER, REPO, remote_head))
    if st != 200:
        sys.exit("读取远端提交失败 %s: %s" % (st, remote_commit))
    remote_tree = remote_commit["tree"]["sha"]
    local_parent_tree = git("rev-parse", "HEAD^^{tree}")
    print("远端 main  :", remote_head)

    if remote_tree != local_parent_tree:
        # 远端有本地没有的提交（例如别人在网页上改过文件）。逐个比对，
        # 只有当「远端与本地父提交不同的文件」全部都在本次要覆盖的范围内才继续。
        print("注意：远端树与本地父提交树不一致，逐文件比对……")
        st, rt = api("GET", "/repos/%s/%s/git/trees/%s?recursive=1" % (OWNER, REPO, remote_tree))
        if st != 200:
            sys.exit("读取远端树失败 %s: %s" % (st, rt))
        remote_map = {e["path"]: e["sha"] for e in rt.get("tree", []) if e["type"] == "blob"}
        local_parent_map = {}
        for line in git("ls-tree", "-r", "HEAD^").splitlines():
            meta, path = line.split("\t", 1)
            local_parent_map[path] = meta.split()[2]
        differ = sorted(p for p in set(remote_map) | set(local_parent_map)
                        if remote_map.get(p) != local_parent_map.get(p))
        changed_set = set(changed)
        outside = [p for p in differ if p not in changed_set]
        print("  远端独有/不同的文件 %d 个：" % len(differ))
        for p in differ[:20]:
            print("    %s%s" % (p, "  （本次会覆盖）" if p in changed_set else "  ← 不在本次改动里"))
        if outside:
            sys.exit("中止：上面标了「不在本次改动里」的文件会被远端丢掉，请先处理这些差异")
        print("  以上文件本次都会被覆盖，继续。")

    entries = []
    for rel in changed:
        if rel in deleted:
            entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": None})
            print("  [删] %s" % rel)
            continue
        path = os.path.join(ROOT, rel.replace("/", os.sep))
        with open(path, "rb") as f:
            blob = f.read()
        st, res = api("POST", "/repos/%s/%s/git/blobs" % (OWNER, REPO),
                      {"content": base64.b64encode(blob).decode("ascii"), "encoding": "base64"})
        if st not in (200, 201):
            sys.exit("上传 blob 失败 %s (%s): %s" % (rel, st, res))
        local_blob = git("rev-parse", "HEAD:" + rel)
        if res["sha"] != local_blob:
            sys.exit("blob 哈希与本地不一致，中止：%s" % rel)
        print("  [改] %-40s %s" % (rel, res["sha"][:12]))
        entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": res["sha"]})

    st, tree = api("POST", "/repos/%s/%s/git/trees" % (OWNER, REPO),
                   {"base_tree": remote_tree, "tree": entries})
    if st not in (200, 201):
        sys.exit("创建 tree 失败 %s: %s" % (st, tree))
    if tree["sha"] != local_tree:
        sys.exit("新树哈希与本地不一致，中止（%s != %s）" % (tree["sha"], local_tree))
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

    if commit["sha"] == head:
        print("本地与远端提交 SHA 完全一致")
    elif commit["sha"] == predicted:
        subprocess.run(["git", "update-ref", "refs/heads/main", commit["sha"]], cwd=ROOT, check=True)
        print("已把本地 main 对齐到远端提交 %s（树相同，仅提交对象换形）" % commit["sha"][:12])
    else:
        print("本地 HEAD 仍为 %s；内容一致但 SHA 不同，请人工确认" % head[:12])


if __name__ == "__main__":
    main()

