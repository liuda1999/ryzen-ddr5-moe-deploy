# -*- coding: utf-8 -*-
"""发布 GitHub Release 并上传附件。

配套工具：make_release.py 负责打 zip，本脚本负责建 tag 与上传。

用法：
    set GITHUB_TOKEN=github_pat_xxx
    python publish_release.py ^
        --repo liuda1999/qwen3.6-35b-a3b-cpu-deploy ^
        --tag v0.1.0 ^
        --name 0.1.0 ^
        --body releases\\0.1.0.md ^
        --asset ..\\..\\llm-cpp-release\\qwen3.6-35b-a3b-cpu-deploy-0.1.0-no-model.zip

令牌来源优先级：--token > 环境变量 GITHUB_TOKEN > 环境变量 GH_TOKEN。
**不要把令牌写进本文件或任何会被提交的地方。**

常用参数：
    --dry-run        只打印将要提交的内容，不真正调用接口
    --draft          建为草稿，确认无误后再到网页发布
"""
import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
UPLOAD = "https://uploads.github.com"

# 不走系统 HTTP 代理（有些环境里代理会拦 GitHub 的上传接口）
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(url, token, data=None, method="GET", ctype="application/json"):
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "publish-release-script",
        "Content-Type": ctype,
    }
    if isinstance(data, str):
        data = data.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=300) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("  [失败] HTTP %s  %s" % (e.code, url))
        print("  " + e.read().decode("utf-8", "replace")[:600].replace("\n", "\n  "))
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--repo", required=True, help="owner/repo")
    ap.add_argument("--tag", required=True, help="如 v0.1.0")
    ap.add_argument("--name", help="Release 标题，默认与 tag 相同")
    ap.add_argument("--body", help="Release 说明的 markdown 文件")
    ap.add_argument("--asset", action="append", default=[], help="附件路径，可重复")
    ap.add_argument("--target", default="main", help="目标分支，默认 main")
    ap.add_argument("--draft", action="store_true", help="建为草稿")
    ap.add_argument("--prerelease", action="store_true")
    ap.add_argument("--token", help="令牌（不建议用，优先用环境变量）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    token = (a.token or os.environ.get("GITHUB_TOKEN")
             or os.environ.get("GH_TOKEN") or "").strip()
    if not token:
        print("*** 没有拿到令牌：请设置环境变量 GITHUB_TOKEN")
        sys.exit(2)

    body = ""
    if a.body:
        if not os.path.isfile(a.body):
            print("*** 说明文件不存在:", a.body)
            sys.exit(2)
        body = io.open(a.body, encoding="utf-8").read()

    for p in a.asset:
        if not os.path.isfile(p):
            print("*** 附件不存在:", p)
            sys.exit(2)

    print("仓库     :", a.repo)
    print("tag      :", a.tag)
    print("标题     :", a.name or a.tag)
    print("说明     :", "%d 字符%s" % (len(body), "（来自 %s）" % a.body if a.body else "（空）"))
    print("附件     :", len(a.asset), "个")
    for p in a.asset:
        print("           %s  (%.1f MB)" % (os.path.basename(p), os.path.getsize(p) / 1024 / 1024))
    if a.dry_run:
        print("\n[dry-run] 未调用任何接口。")
        return

    print("\n=== 创建 Release ===")
    payload = json.dumps({
        "tag_name": a.tag,
        "target_commitish": a.target,
        "name": a.name or a.tag,
        "body": body,
        "draft": bool(a.draft),
        "prerelease": bool(a.prerelease),
    })
    rel = call("%s/repos/%s/releases" % (API, a.repo), token, payload, "POST")
    rid = rel["id"]
    print("  成功  Release ID = %s" % rid)
    print("  页面  %s" % rel["html_url"])

    for p in a.asset:
        name = os.path.basename(p)
        print("\n=== 上传附件 %s ===" % name)
        with open(p, "rb") as f:
            blob = f.read()
        url = "%s/repos/%s/releases/%d/assets?name=%s" % (UPLOAD, a.repo, rid, name)
        res = call(url, token, blob, "POST", "application/octet-stream")
        print("  成功  %.1f MB" % (res["size"] / 1024 / 1024))
        print("  %s" % res["browser_download_url"])


if __name__ == "__main__":
    main()
