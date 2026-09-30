"""data.json から X 投稿文を作る。

- posts.txt        … 投稿文をテキストで保存（コピー用）
- docs/posts.html  … スマホで開いて「Xで投稿」を押すだけで投稿画面が開くページ

並び順：まとめ → ⭐おすすめ → 最近伸びている → 終了間近 → 新着 → テーマ紹介
（同じ署名は一番上の区分にだけ出す）

使い方:  python post.py
"""
import html
import re
from datetime import date, timedelta

from build import HERE, SHARE_JS, growth, load_config, load_data, published_items, share_text

LIMIT = 140        # 投稿文の上限（リンク込みで140字）
URL_WEIGHT = 23    # X ではリンクはどんな長さでも23字として数えられる
RISING_TOP = 5     # 「最近伸びている」に出す件数
NEW_DAYS = 8       # 見つけてから何日以内を「新着」とするか（週1回の実行に合わせる）


def length(text):
    """リンクを23字として、投稿文の文字数を数える。"""
    urls = re.findall(r"https?://\S+", text)
    rest = re.sub(r"https?://\S+", "", text)
    return len(urls) * URL_WEIGHT + len(rest)


def main():
    config = load_config()
    data = load_data()
    items = published_items(data)
    site, main_tag = config["site_url"], config["main_hashtag"]
    hashtag_of = {t["name"]: t["hashtag"] for t in config["tags"]}
    today = date.today()
    share = lambda it: share_text(it, main_tag, hashtag_of)

    posts = []  # (見出し, 本文)
    used = set()

    def add(label, its):
        for it in its:
            if it["id"] not in used:
                used.add(it["id"])
                posts.append((f"{label}｜{'・'.join(it['tags'])}", share(it)))

    posts.append(("まとめ", (
        f"いま賛同を集めている署名を{len(items)}件まとめました✍️\n"
        f"{'、'.join(t['name'] for t in config['tags'][:3])}など、暮らしに身近なテーマも。\n"
        f"気になるものから一筆を🙏\n"
        f"{site}\n{main_tag}"
    )))

    add("⭐おすすめ", [it for it in items if it.get("pick")])

    rising = sorted([it for it in items if growth(it) and growth(it)[0] > 0], key=lambda it: growth(it)[2], reverse=True)
    add("最近伸びている", rising[:RISING_TOP])

    soon = (today + timedelta(days=config["urgent_days"])).isoformat()
    add("終了間近", sorted([it for it in items if it.get("end") and it["end"] <= soon], key=lambda it: it["end"]))

    new_since = (today - timedelta(days=NEW_DAYS)).isoformat()
    add("新着", [it for it in items if it.get("found", "") >= new_since])

    for t in config["tags"]:
        its = [it for it in items if t["name"] in it["tags"]]
        if not its:
            continue
        posts.append((f"テーマ紹介｜{t['name']}", (
            f"「{t['name']}」について、いま{len(its)}件の署名が賛同を集めています✍️\n"
            f"どんな声が上がっているか、のぞいてみませんか？\n"
            f"{site}\n{main_tag} {t['hashtag']}".rstrip()
        )))

    write_outputs(posts, data.get("updated", ""), config)


def write_outputs(posts, updated, config):
    txt = [f"X投稿文（署名数の確認日 {updated}）", ""]
    for i, (label, body) in enumerate(posts, 1):
        txt += [f"===== {i}. {label}（{length(body)}/{LIMIT}字） =====", body, ""]
    (HERE / "posts.txt").write_text("\n".join(txt), encoding="utf-8")

    cards = []
    for label, body in posts:
        cards.append(
            f'<section><h2>{html.escape(label)} <small>{length(body)}/{LIMIT}字</small></h2>'
            f'<pre>{html.escape(body)}</pre>'
            f'<div class="btns"><button type="button" class="x" onclick="post(this)">𝕏アプリで投稿</button>'
            f'<button type="button" onclick="copy(this)">コピー</button></div></section>'
        )
    page = POSTS_TEMPLATE.replace("__UPDATED__", html.escape(updated))
    page = page.replace("__SHARE_JS__", SHARE_JS)
    page = page.replace("__SITE_NAME__", html.escape(config["site_name"])).replace("__CARDS__", "\n".join(cards))
    (HERE / "docs").mkdir(exist_ok=True)
    (HERE / "docs" / "posts.html").write_text(page, encoding="utf-8")
    print(f"posts.txt と docs/posts.html を作りました（投稿文 {len(posts)} 本）")



POSTS_TEMPLATE = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>X投稿文｜__SITE_NAME__</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1c1b19;--sub:#5f5c56;--line:#e3e0d9}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#16161a;--card:#202026;--ink:#ecebe8;--sub:#a8a59f;--line:#34343c}}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Hiragino Sans","Noto Sans JP","Meiryo",sans-serif}
.wrap{max-width:640px;margin:0 auto;padding:16px}
h1{font-size:1.3rem;margin:8px 0 2px}
p{color:var(--sub);font-size:.88rem;margin:0 0 12px}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:12px 0}
h2{font-size:.95rem;margin:0 0 6px}
h2 small{color:var(--sub);font-weight:400}
pre{white-space:pre-wrap;word-break:break-all;font-family:inherit;font-size:.9rem;margin:0 0 10px;line-height:1.6}
.btns{display:flex;gap:8px}
.btns a,.btns button{flex:1;text-align:center;padding:9px;border-radius:8px;font-size:.9rem;font-weight:700;
  text-decoration:none;border:1px solid var(--line);font-family:inherit;cursor:pointer}
.x{background:var(--ink);color:var(--bg)}
button{background:var(--card);color:var(--ink)}
</style></head>
<body><div class="wrap">
<p><a href="./">← 署名の一覧</a></p>
<h1>X投稿文</h1>
<p>署名数の確認日：__UPDATED__。「𝕏アプリで投稿」を押すと、文章が入った状態でXの投稿画面が開きます。内容を確認してから投稿してください。</p>
__CARDS__
</div>
<script>
__SHARE_JS__
function post(btn){ shareX(btn.closest('section').querySelector('pre').textContent); }
function copy(btn){
  const text = btn.closest('section').querySelector('pre').textContent;
  navigator.clipboard.writeText(text).then(() => { btn.textContent = 'コピーしました'; setTimeout(() => btn.textContent = 'コピー', 1500); });
}
</script>
</body></html>
"""

if __name__ == "__main__":
    main()
