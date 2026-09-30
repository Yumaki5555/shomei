"""スクショ撮影 → 一覧ページ作成 → X投稿文作成 → GitHub へ送る（公開）を1回で行う。

使い方:  python publish.py
         python publish.py --no-push   （公開せず、手元でページを作るだけ）
"""
import argparse
import subprocess
import time
from datetime import date
from pathlib import Path

import build
import post
import shots

HERE = Path(__file__).parent


def git(*args):
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true", help="GitHubに送らない")
    args = ap.parse_args()

    shots.main()
    build.main()
    post.main()
    print(f"手元で確認するには、{HERE / 'docs' / 'index.html'} をダブルクリックしてください。")

    if args.no_push:
        return
    if not (HERE / ".git").exists():
        print("まだGitHubとつながっていないので、公開はしていません（README.md の「公開する」を参照）。")
        return
    # Dropboxが同期中だと失敗することがあるので、少し待って何度か試す
    for attempt in range(5):
        r = git("add", "-A")
        if r.returncode == 0:
            break
        time.sleep(3)
    else:
        print("保存の準備（git add）に失敗しました。少し待ってからもう一度実行してください：\n" + r.stdout + r.stderr)
        return
    if git("diff", "--cached", "--quiet").returncode != 0:
        r = git("commit", "-m", f"署名の更新 {date.today().isoformat()}")
        if r.returncode != 0:
            print("保存（コミット）に失敗しました：\n" + r.stdout + r.stderr)
            return
    # 保存したけれど、まだGitHubに送っていないものがあるか
    ahead = git("rev-list", "--count", "@{u}..HEAD").stdout.strip()
    if ahead == "0":
        print("変更がないので、公開は不要でした。")
        return
    r = git("push")
    if r.returncode != 0:
        print("GitHubへの送信に失敗しました：\n" + r.stdout + r.stderr)
        return
    print("GitHubに送りました。数分後に公開ページに反映されます。")


if __name__ == "__main__":
    main()
