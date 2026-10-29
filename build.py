"""data.json から公開用のページを作る。

- docs/index.html   … 一覧ページ
- docs/p/番号.html  … 1件ごとのまとめページ（スクショ・署名数の推移グラフつき）
- docs/sites.html   … 署名サイト（Voice と change.org）の違いの説明ページ
- docs/style.css    … すべてのページで共通の見た目（色・文字・ボタン）
- docs/illust/      … しょめたんのイラスト（illust.py が元の絵から切り抜く）

載せるのは「掲載」になっている署名だけ（「候補」「非掲載」「終了」は載せない）。

使い方:  python build.py
"""
import hashlib
import html
import json
from datetime import date
from pathlib import Path

import illust
from collect import PREFS

HERE = Path(__file__).parent
OUT_DIR = HERE / "docs"


def load_config():
    return json.loads((HERE / "config.json").read_text(encoding="utf-8"))


def load_data():
    return json.loads((HERE / "data.json").read_text(encoding="utf-8"))


def published_items(data):
    return [it for it in data["items"].values() if it["status"] == "掲載"]


def sorted_counts(it):
    """署名数の記録を日付の古い順に並べた [(日付, 人数), ...]。"""
    return sorted(it["counts"].items())


def latest_count(it):
    c = sorted_counts(it)
    return c[-1][1] if c else None


def latest_count_date(it):
    """いちばん新しい署名数を確認した日。記録が無ければ空文字。"""
    c = sorted_counts(it)
    return c[-1][0] if c else ""


def growth(it):
    """前回の記録からの増え方。(増えた人数, 前回の日付, 1日あたり) または None。"""
    c = sorted_counts(it)
    if len(c) < 2:
        return None
    (d0, n0), (d1, n1) = c[-2], c[-1]
    days = max((date.fromisoformat(d1) - date.fromisoformat(d0)).days, 1)
    return n1 - n0, d0, (n1 - n0) / days


def page_name(it):
    return it["id"].replace(":", "-") + ".html"


def summary_path(it):
    return "p/" + page_name(it)


def image_of(it):
    """スクショがあればそれを、なければ署名サイトの紹介画像を使う。"""
    return it.get("image") or it.get("photo") or ""


def site_label(it):
    return "change.org" if it["site"] == "Change" else "Voice"


def md(iso):
    d = date.fromisoformat(iso)
    return f"{d.month}/{d.day}"


def md_jp(iso):
    """「2026-10-05」→「10月5日」。"""
    d = date.fromisoformat(iso)
    return f"{d.month}月{d.day}日"


def ymd_jp(iso):
    """「2026-10-05」→「2026年10月5日」。日付が無ければ空文字。"""
    if not iso:
        return ""
    d = date.fromisoformat(iso)
    return f"{d.year}年{d.month}月{d.day}日"


def share_text(it, main_hashtag, hashtag_of):
    """1件ごとの投稿の定型文（一覧ページの「𝕏でシェア」と投稿文ページで共通）。
    リンクは署名ページそのもの（見た人がすぐ署名できるように）。
    リンク（23字として数える）込みで140字以内にする。"""
    tags = " ".join([main_hashtag] + [hashtag_of[t] for t in it["tags"] if hashtag_of.get(t)])
    head = "⭐【おすすめ署名】" if it.get("pick") else "✍️【署名募集中】"
    n = latest_count(it)
    people = f"いま{n:,}人が賛同しています。\n" if n else ""
    end = date.fromisoformat(it["end"]) if it.get("end") else None
    until = f"（{end.year}/{end.month}/{end.day}まで）" if end else ""
    make = lambda title: (f"{head}{until}\n\n「{title}」\n\n{people}"
                          f"あなたも一筆を🙏\n{tags}\n\n")
    title = it["title"]
    while len(make(title)) + 23 > 140 and len(title) > 8:
        title = title[:-2].rstrip("…") + "…"
    return make(title) + it["url"]


SHARE_JS = r"""
// スマホではXアプリを直接開く（アプリ内ブラウザで毎回ログインを求められないように）。
// アプリが開かなかったときだけ、1.5秒後にブラウザ版Xを開く。
function shareX(text){
  const web = 'https://x.com/intent/post?text=' + encodeURIComponent(text);
  if (!/Android|iPhone|iPad|iPod/i.test(navigator.userAgent)) { window.open(web, '_blank', 'noopener'); return; }
  const fallback = setTimeout(() => { if (!document.hidden) location.href = web; }, 1500);
  document.addEventListener('visibilitychange', () => { if (document.hidden) clearTimeout(fallback); }, { once: true });
  location.href = 'twitter://post?message=' + encodeURIComponent(text);
}
"""

# 「署名した」の記録は、見ている人のブラウザの中（localStorage）だけに保存する。
# 使えない環境（プライベートブラウズなど）でも、ページはふつうに動くようにしておく。
SIGNED_JS = r"""
const SIGNED_KEY = 'shomei-signed';
function loadSigned(){ try { return JSON.parse(localStorage.getItem(SIGNED_KEY) || '{}') || {}; } catch (e) { return {}; } }
function saveSigned(s){ try { localStorage.setItem(SIGNED_KEY, JSON.stringify(s)); } catch (e) {} }
function toggleSigned(id){
  const s = loadSigned();
  if (s[id]) delete s[id]; else s[id] = new Date().toISOString().slice(0, 10);
  saveSigned(s);
  return !!s[id];
}
"""

# 「ページの上へ」ボタンと、短いお知らせ（トースト）。どのページでも同じものを使う。
COMMON_JS = r"""
(function(){
  // ページ下の帯が見えているあいだは隠す（帯の中の「上へ戻る」と重ならないように）
  const b = document.getElementById('totop'), f = document.querySelector('.footer');
  if (!b) return;
  let atFooter = false;
  const paint = () => b.classList.toggle('show', scrollY > 600 && !atFooter);
  if (f && 'IntersectionObserver' in window) new IntersectionObserver(es => { atFooter = es[0].isIntersecting; paint(); }).observe(f);
  addEventListener('scroll', paint, { passive: true });
})();
function toast(msg){
  const t = document.getElementById('toast'); if (!t) return;
  t.textContent = msg; t.classList.add('show');
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 2000);
}
"""

# 外部サイトへのリンクにつける印（四角から矢印が出るマーク）
EXT_ICON = ('<svg class="ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" '
            'd="M14 3h7v7h-2V6.41l-8.29 8.3-1.42-1.42L17.59 5H14V3zM5 5h6v2H5v12h12v-6h2v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"/></svg>')

# サイトのアイコン（パープルの地に白い署名用紙とペン）。絵は favicon.py で作る。
# theme-color は、スマホのブラウザの上の帯の色（ページ上の帯と同じパープル）。
FAVICON = """<link rel="icon" href="{root}favicon.ico" sizes="48x48">
<link rel="icon" href="{root}favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="{root}apple-touch-icon.png">
<meta name="theme-color" content="#7548a3">"""

CHARA_SRC = HERE / "しょめたん"
CHARA_OUT = OUT_DIR / "chara"


def chara_path(filename):
    """しょめたんの絵を、ページ用に軽くした画像（横800pxのJPEG）にして docs/chara/ に置く。
    作ったあとの場所（docs からの相対パス）を返す。絵が無ければ空文字。"""
    if not filename:
        return ""
    src = CHARA_SRC / filename
    if not src.exists():
        print(f"  注意：しょめたんの絵「{filename}」が見つかりません")
        return ""
    name = hashlib.md5(filename.encode("utf-8")).hexdigest()[:10] + ".jpg"
    out = CHARA_OUT / name
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        from PIL import Image

        CHARA_OUT.mkdir(parents=True, exist_ok=True)
        img = Image.open(src)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (251, 247, 240))  # 絵の背景に近いクリーム色
            bg.paste(img, mask=img.split()[-1])
            img = bg
        img = img.convert("RGB")
        if img.width > 800:
            img = img.resize((800, round(img.height * 800 / img.width)), Image.LANCZOS)
        img.save(out, "JPEG", quality=82, optimize=True)
    return f"chara/{name}"


def illust_img(root, name, alt, cls="", loading="lazy"):
    """docs/illust/ のイラストの <img>。大きさを書いておき、読みこみ中にページがずれないようにする。"""
    w, h = illust.size_of(name)
    c = f' class="{cls}"' if cls else ""
    return (f'<img{c} src="{root}illust/{name}.webp" alt="{html.escape(alt)}" width="{w}" height="{h}"'
            f' loading="{loading}" decoding="async">')


def page_head(root):
    """どのページにも入れる、共通の見た目（style.css）とアイコン。"""
    return f'<link rel="stylesheet" href="{root}style.css?v={CSS_VER}">\n' + FAVICON.format(root=root)


def topbar(root, site_name, on_top=False):
    """ページ上の帯（サイト名と、よく使うページへのリンク）。"""
    top = root or "./"
    home = "" if on_top else top
    return f"""<header class="topbar"><div class="wrap">
<a class="logo" href="{top}"><img src="{root}illust/icon.webp" alt="" width="40" height="40">{html.escape(site_name)}</a>
<nav class="nav" aria-label="サイト内のリンク"><a href="{home}#search">さがす</a><a href="{home}#howto">署名のしかた</a><a href="{home}#notes">注意事項</a><a href="{root}sites.html">サイトの違い</a></nav>
</div></header>"""


def footer(root, on_top=False):
    """ページ下の帯（出典・注意・リンク）と「上へ」ボタン。"""
    top = root or "./"
    home = "" if on_top else top
    return f"""<footer class="footer"><div class="wrap">
<ul class="footer-links">
  <li><a href="{top}">署名の一覧</a></li>
  <li><a href="{home}#howto">署名のしかた</a></li>
  <li><a href="{home}#notes">注意事項</a></li>
  <li><a href="{root}sites.html">署名サイトの違い（Voice と change.org）</a></li>
  <li><a href="{root}posts.html">📣 X投稿文ページ</a></li>
</ul>
<p>出典：<a href="https://www.change.org/" target="_blank" rel="noopener">change.org</a>・<a href="https://voice.charity/" target="_blank" rel="noopener">Voice</a> の公開情報。
署名数は当サイトが確認した日の人数で、最新の人数とは異なる場合があります。必ず署名ページで内容をご確認ください。</p>
<p>この掲示板に載っていても、署名の内容に賛成・保証するものではありません。</p>
<p class="footer-top"><a class="btn btn-sub" href="#top">↑ ページのいちばん上へ戻る</a></p>
</div></footer>
<a class="totop" id="totop" href="#top" aria-label="ページのいちばん上へ戻る"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M12 5.6 4.3 13.3l1.4 1.4L11 9.4V20h2V9.4l5.3 5.3 1.4-1.4z"/></svg><span>上へ</span></a>
<div class="toast" id="toast" role="status" aria-live="polite"></div>"""


def main():
    config = load_config()
    data = load_data()
    items = published_items(data)
    tags = config["tags"]
    hashtag_of = {t["name"]: t["hashtag"] for t in tags}
    known = {t["name"] for t in tags}
    # config.json に無いタグは灰色で表示する
    for it in items:
        for t in it["tags"]:
            if t not in known:
                tags.append({"name": t, "color": "#6b7280", "hashtag": ""})
                known.add(t)

    illust.make_all()
    write_css()

    rows = []
    for it in items:
        g = growth(it)
        rows.append({
            "id": it["id"], "site": it["site"], "url": it["url"], "title": it["title"],
            "summary": it.get("summary", ""),
            "starter": it.get("starter", ""), "target": it.get("target", ""),
            "start": it.get("start", ""), "end": it.get("end", ""),
            "tags": it["tags"], "pref": it.get("pref", ""), "pick": bool(it.get("pick")), "rank": it.get("pick_rank") or 999,
            "found": it.get("found", ""), "count": latest_count(it), "countDate": latest_count_date(it),
            "grow": g[0] if g else None, "growFrom": g[1] if g else None, "rate": g[2] if g else 0,
            "page": summary_path(it), "share": share_text(it, config["main_hashtag"], hashtag_of),
        })
    build_summary_pages(items, tags, config, hashtag_of)

    chara_all = chara_path(config.get("chara_all", ""))
    oops_w, oops_h = illust.size_of("oops")
    payload = {
        "updated": data.get("updated", ""),
        "items": rows,
        "tags": [{"name": t["name"], "color": t["color"], "chara": chara_path(t.get("chara", ""))} for t in tags],
        "charaAll": chara_all,
        "charaPick": chara_path(config.get("chara_pick", "")),
        "urgentDays": config["urgent_days"],
        "prefs": PREFS,
        "oops": {"src": "illust/oops.webp", "w": oops_w, "h": oops_h},
    }
    page = TEMPLATE
    for key, value in {
        "__HEAD__": page_head(""),
        "__TOPBAR__": topbar("", config["site_name"], on_top=True),
        "__FOOTER__": footer("", on_top=True),
        "__HERO_IMG__": illust_img("", "hero", "署名用紙をかかえた、しょめたん（署名をあつめる妖精）", loading="eager"),
        "__IMG_SEARCH__": illust_img("", "search", "虫めがねで署名をさがす、しょめたん", "panel-illust"),
        "__IMG_STEP1__": illust_img("", "search", "虫めがねで署名をさがす、しょめたん"),
        "__IMG_STEP2__": illust_img("", "check", "署名用紙を見て「え？」と確かめる、しょめたん"),
        "__IMG_STEP3__": illust_img("", "sign", "しょめたんの署名用紙に、鳥さんが署名しているところ"),
        "__IMG_THANKS__": illust_img("", "thanks", "署名用紙をかかえて、よろこぶしょめたん"),
        "__IMG_PLEASE__": illust_img("", "please", "手をあわせて「確かめてね」とおねがいする、しょめたん"),
        "__SITE_NAME__": html.escape(config["site_name"]),
        "__SITE_DESC__": html.escape(config["site_description"]),
        "__SITE_URL__": html.escape(config["site_url"]),
        "__COUNT__": str(len(items)),
        # 「2026年」と「10月20日」の間でだけ折り返す
        "__UPDATED_JP__": ymd_jp(data.get("updated", "")).replace("年", '年</span><span class="nw">', 1).join(['<span class="nw">', "</span>"]),
        "__UPDATE_NOTE__": html.escape(config.get("update_note", "")),
        "__OG_IMAGE__": f'<meta property="og:image" content="{html.escape(config["site_url"] + chara_all)}">' if chara_all else "",
        "__EXT_ICON__": EXT_ICON,
        "__COMMON_JS__": COMMON_JS,
        "__SIGNED_JS__": SIGNED_JS,
        "__SHARE_JS__": SHARE_JS,
        "__DATA__": json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"),
    }.items():
        page = page.replace(key, value)

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "index.html").write_text(page, encoding="utf-8")
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    build_sites_page(config)
    print(f"docs/index.html を作りました（掲載 {len(items)} 件）")


def chart_svg(it):
    """署名数の推移を、外部の部品を使わない簡単な線グラフ（SVG）にする。"""
    c = sorted_counts(it)
    if len(c) < 2:
        return '<p class="note">署名数の記録がたまると、ここに推移のグラフが出ます。</p>'
    W, H, L, R, T, B = 600, 220, 64, 16, 16, 34
    d0 = date.fromisoformat(c[0][0])
    span = max((date.fromisoformat(c[-1][0]) - d0).days, 1)
    lo, hi = min(n for _, n in c), max(n for _, n in c)
    if hi == lo:
        hi = lo + 1
    x = lambda d: L + (date.fromisoformat(d) - d0).days / span * (W - L - R)
    y = lambda n: T + (1 - (n - lo) / (hi - lo)) * (H - T - B)
    pts = " ".join(f"{x(d):.1f},{y(n):.1f}" for d, n in c)
    dots = "".join(f'<circle cx="{x(d):.1f}" cy="{y(n):.1f}" r="4.5"><title>{md(d)}：{n:,}人</title></circle>' for d, n in c)
    labels = (f'<text x="{L - 6}" y="{y(hi) + 4:.1f}" text-anchor="end">{hi:,}</text>'
              f'<text x="{L - 6}" y="{y(lo) + 4:.1f}" text-anchor="end">{lo:,}</text>'
              f'<text x="{L}" y="{H - 10}">{md(c[0][0])}</text>'
              f'<text x="{W - R}" y="{H - 10}" text-anchor="end">{md(c[-1][0])}</text>')
    grid = f'<line x1="{L}" y1="{H - B}" x2="{W - R}" y2="{H - B}" class="axis"/>'
    return (f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="署名数の推移">'
            f'{grid}<polyline points="{pts}"/>{dots}{labels}</svg>')


def build_summary_pages(items, tag_defs, config, hashtag_of):
    """1件ごとのまとめページ（docs/p/番号.html）を作る。載せなくなったページは消す。"""
    out = OUT_DIR / "p"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.html"):
        old.unlink()
    color_of = {t["name"]: t["color"] for t in tag_defs}
    e = html.escape
    site_url = config["site_url"]
    please = illust_img("../", "please", "手をあわせて「確かめてね」とおねがいする、しょめたん")

    for it in items:
        n = latest_count(it)
        g = growth(it)
        img = image_of(it)
        img_abs = img if img.startswith("http") else (site_url + img if img else "")
        img_rel = img if img.startswith("http") else ("../" + img if img else "")
        site = site_label(it)
        facts = [("発起人", it.get("starter")), ("提出先", it.get("target")),
                 ("開始日", ymd_jp(it.get("start"))), ("終了日", ymd_jp(it.get("end"))),
                 ("目標", f"{it['goal']:,}人" if it.get("goal") else ""),
                 ("署名サイト", site)]
        facts_html = "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in facts if v)
        grow_html = (f'<span class="grow">前回（{md_jp(g[1])}）から +{g[0]:,}人</span>' if g and g[0] > 0 else "")
        count_html = (f'<div class="countbox"><span class="k">賛同した人の数</span>'
                      f'<span class="num">{n:,}</span> 人 <span class="when">（{ymd_jp(latest_count_date(it))} 確認）</span>'
                      f'{grow_html}</div>') if n else ""
        desc = f"いま{n:,}人が賛同。{it.get('summary', '')}" if n else it.get("summary", "")
        replace = {
            "__HEAD__": page_head("../"),
            "__TOPBAR__": topbar("../", config["site_name"]),
            "__FOOTER__": footer("../"),
            "__PLEASE_IMG__": please,
            "__TITLE__": e(it["title"]),
            "__PICK__": '<span class="badge pick">⭐ おすすめ</span>' if it.get("pick") else "",
            "__TAGS__": "".join(f'<span class="badge"><span class="dot" style="background:{color_of.get(t, "#6b7280")}"></span>{e(t)}</span>'
                                for t in it["tags"]),
            "__PREF__": f'<span class="badge">📍 {e(it["pref"])}</span>' if it.get("pref") else "",
            "__SITEBADGE__": f'<span class="badge {"change" if it["site"] == "Change" else "voice"}">{site}</span>',
            "__IMG__": f'<img class="shot" src="{e(img_rel)}" alt="署名ページの画面" loading="lazy">' if img_rel else "",
            "__COUNTBOX__": count_html,
            "__SUMMARY__": e(it.get("summary", "")),
            "__FACTS__": facts_html,
            "__CHART__": chart_svg(it),
            "__URL__": e(it["url"]),
            "__SITE__": site,
            "__EXT_ICON__": EXT_ICON,
            "__END_ISO__": e(it.get("end") or ""),
            "__SHARE__": json.dumps(share_text(it, config["main_hashtag"], hashtag_of), ensure_ascii=False).replace("</", "<\\/"),
            "__COMMON_JS__": COMMON_JS,
            "__SHARE_JS__": SHARE_JS,
            "__SIGNED_JS__": SIGNED_JS,
            "__ID__": json.dumps(it["id"]),
            "__CHANGE_NOTE__": ("<li><b>change.org の署名です</b>内容をよく確かめたうえで、ご自身で判断してください。</li>"
                                if it["site"] == "Change" else ""),
            "__SITE_NAME__": e(config["site_name"]),
            "__PAGE_URL__": e(site_url + summary_path(it)),
            "__OG_IMAGE__": f'<meta property="og:image" content="{e(img_abs)}">' if img_abs else "",
            "__CARD__": "summary_large_image" if img_abs else "summary",
            "__DESC__": e(desc[:120]),
            "__URGENT_DAYS__": str(config["urgent_days"]),
        }
        page = SUMMARY_TEMPLATE
        for k, v in replace.items():
            page = page.replace(k, v)
        (out / page_name(it)).write_text(page, encoding="utf-8")


# すべてのページで共通の見た目。docs/style.css に書き出す。
# 白が基本・パープル（#7548A3）がメインの色。文字は大きめ（スマホ17px・パソコン18px）。ボタンはどれも同じ高さ・角丸・余白。
# 「署名済み」の印と、署名数が増えた数は、意味のある色として緑（--ok）のまま。
BASE_CSS = r"""
:root{--brand:#7548a3;--brand-dark:#613a8c;--brand-deep:#482a6b;--brand-soft:#e9def5;--brand-pale:#f6f1fb;--brand-line:#c6afe0;
  --ok:#15803d;--ok-deep:#14532d;--ok-soft:#dcfce7;
  --ink:#1f2937;--sub:#4b5563;--line:#e6dfed;--field:#cdc3d8;--bg:#fff;--bg-soft:#f7f5f9;
  --pick:#926000;--pick-bg:#fff3d7;--urgent:#b91c1c;--urgent-bg:#fef2f2;
  --sv-bg:#ffe4e6;--sv-ink:#9f1239;--sc-bg:#fef9c3;--sc-ink:#713f12;
  --radius:16px;--btn-h:50px;color-scheme:light}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{font-size:106.25%;-webkit-text-size-adjust:100%;scroll-padding-top:80px}
@media (min-width:768px){html{font-size:112.5%}}
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP","Yu Gothic UI","Meiryo",sans-serif;line-height:1.75;overflow-wrap:break-word}
img{max-width:100%;height:auto}
a{color:var(--brand-dark);text-underline-offset:.2em}
a:hover{color:var(--brand-deep)}
:focus-visible{outline:3px solid #9a6bcc;outline-offset:2px}
h1,h2,h3{line-height:1.45}
.wrap{max-width:1120px;margin:0 auto;padding:0 16px}
.nw{display:inline-block}
.note{font-size:.88rem;color:var(--sub)}

/* ページ上の帯（パープルの帯に白い文字） */
.topbar{background:var(--brand);color:#fff}
.topbar .wrap{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:0 12px;padding-top:4px;padding-bottom:4px}
.topbar a:hover{color:#fff}
.topbar :focus-visible{outline-color:#fff}
.logo{display:inline-flex;align-items:center;gap:8px;min-height:48px;font-size:1.15rem;font-weight:800;color:#fff;text-decoration:none;letter-spacing:.04em}
.logo img{width:40px;height:40px;object-fit:contain}
.nav{display:flex;flex-wrap:wrap;gap:2px;margin:0 -8px}
.nav a{display:inline-flex;align-items:center;min-height:44px;padding:2px 10px;border-radius:999px;font-size:.9rem;font-weight:700;color:#fff;text-decoration:none}
.nav a:hover{background:rgba(255,255,255,.16)}
@media (max-width:520px){
  .nav{width:calc(100% + 12px);margin:0 -6px;justify-content:space-between}
  .nav a{padding:2px 6px;font-size:.82rem}
}
@media (max-width:359px){.nav a:first-child{display:none}}

/* ボタン（すべて同じ高さ・角丸・余白。色は「パープル＝いちばんの行動」「白＝そのほか」の2種類だけ） */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:var(--btn-h);padding:8px 18px;border-radius:12px;border:2px solid transparent;
  font:inherit;font-size:1rem;font-weight:700;line-height:1.35;text-align:center;text-decoration:none;cursor:pointer;-webkit-tap-highlight-color:transparent}
.btn-primary{background:var(--brand);border-color:var(--brand);color:#fff;box-shadow:0 3px 0 var(--brand-deep)}
.btn-primary:hover{background:var(--brand-dark);border-color:var(--brand-dark);color:#fff}
.btn-primary:active{transform:translateY(2px);box-shadow:0 1px 0 var(--brand-deep)}
.btn-sub{background:#fff;border-color:var(--brand-line);color:var(--brand-dark)}
.btn-sub:hover{background:var(--brand-pale);color:var(--brand-deep)}
.btn-sub[aria-pressed="true"]{background:var(--ok-soft);border-color:var(--ok);color:var(--ok-deep)}
/* 署名ページへの誘導ボタン（ほかのボタンより少し大きく・太く、いちばん目立たせる） */
.btn-cta{min-height:58px;font-size:1.1rem;font-weight:800;letter-spacing:.03em;box-shadow:0 4px 0 var(--brand-deep),0 6px 16px rgba(72,42,107,.22)}
.btn:disabled{opacity:.45;cursor:default;box-shadow:none}
.btn-block{display:flex;width:100%}
.btn .ico{width:1.15em;height:1.15em;flex:none}
.btn-row{display:flex;flex-wrap:wrap;gap:8px}
.btn-row .btn{flex:1 1 0;min-width:max-content;padding-left:12px;padding-right:12px}
.ext-note{margin:4px 0 0;font-size:.85rem;color:var(--sub);text-align:center}

/* 小さなラベル（押せない印。ボタンと見分けがつくよう、枠なし・小さめ） */
.badges{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.badge{display:inline-flex;align-items:center;gap:5px;padding:1px 10px;border-radius:8px;background:#f1edf5;color:var(--ink);font-size:.85rem;font-weight:700;line-height:1.7}
.badge .dot{width:.7em;height:.7em;border-radius:50%;flex:none}
.badge.pick{background:var(--pick-bg);color:var(--pick)}
.badge.left.urgent{background:var(--urgent-bg);color:var(--urgent)}
.badge.signed{background:var(--ok);color:#fff}
.badge.voice{background:var(--sv-bg);color:var(--sv-ink)}
.badge.change{background:var(--sc-bg);color:var(--sc-ink)}
.grow{display:block;color:var(--ok);font-weight:700;font-size:.9rem}

/* 見出し・区切り */
.section{padding:44px 0}
.section-h{display:flex;align-items:center;gap:10px;margin:0 0 8px;font-size:1.5rem;color:var(--brand-deep)}
.section-h::before{content:"";flex:none;width:8px;height:1.3em;border-radius:4px;background:var(--brand)}
.section-lead{margin:0 0 20px;color:var(--sub)}
.box{background:#fff;border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px}
.box h2{margin:0 0 8px;font-size:1.2rem;color:var(--brand-deep)}

/* 折りたたみ */
details{background:#fff;border:1px solid var(--line);border-radius:14px;margin:10px 0}
summary{position:relative;display:flex;align-items:center;min-height:54px;padding:10px 52px 10px 18px;font-weight:800;cursor:pointer;list-style:none}
summary::-webkit-details-marker{display:none}
summary::after{content:"＋ ひらく";position:absolute;right:14px;top:50%;transform:translateY(-50%);font-size:.8rem;color:var(--brand-dark);background:var(--brand-pale);border-radius:999px;padding:2px 10px}
details[open] summary::after{content:"－ とじる"}
summary{padding-right:110px}
details>div{padding:0 18px 14px}
details>div p{margin:0 0 8px}
details ul{margin:0 0 8px;padding-left:1.3em}

/* チェックリスト（注意事項） */
.checklist{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px}
.checklist li{position:relative;background:#fff;border:1px solid var(--line);border-radius:14px;padding:12px 14px 12px 52px}
.checklist li::before{content:"✓";position:absolute;left:14px;top:13px;display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:50%;background:var(--brand);color:#fff;font-size:.9rem;font-weight:800}
.checklist b{display:block;color:var(--brand-deep)}

/* ページ下 */
.footer{background:var(--bg-soft);border-top:1px solid var(--line);margin-top:0;padding:28px 0 40px;font-size:.9rem;color:var(--sub)}
.footer-top{margin-top:16px!important;text-align:center}
.footer p{margin:0 0 8px}
.footer-links{display:flex;flex-wrap:wrap;gap:0 18px;margin:0 0 12px;padding:0;list-style:none}
.footer-links a{display:inline-flex;align-items:center;min-height:44px;font-weight:700}
.totop{position:fixed;right:16px;bottom:16px;z-index:20;display:flex;flex-direction:column;align-items:center;justify-content:center;width:58px;height:58px;border-radius:50%;
  background:var(--brand);color:#fff;font-size:.72rem;font-weight:800;line-height:1.1;text-decoration:none;box-shadow:0 4px 14px rgba(72,42,107,.35);
  opacity:0;visibility:hidden;transform:translateY(8px);transition:opacity .2s,transform .2s,visibility .2s}
.totop.show{opacity:1;visibility:visible;transform:none}
.totop:hover{background:var(--brand-dark);color:#fff}
.totop svg{width:24px;height:24px}
.toast{position:fixed;left:50%;bottom:90px;z-index:30;transform:translateX(-50%);max-width:calc(100% - 32px);padding:12px 20px;border-radius:12px;
  background:var(--brand-deep);color:#fff;font-weight:700;text-align:center;opacity:0;transition:opacity .2s;pointer-events:none}
.toast.show{opacity:1}

/* ===== 一覧ページ ===== */
.hero{background:linear-gradient(180deg,var(--brand-pale),#fff);padding:18px 0 30px}
.hero-grid{display:grid;grid-template-columns:minmax(0,1fr);justify-items:center;gap:6px;text-align:center}
.hero h1{margin:0;font-size:2.3rem;letter-spacing:.1em;color:var(--brand-deep)}
.hero-illust{margin:0;width:min(70vw,290px)}
.hero-illust img{display:block;width:100%;height:auto}
.hero-text{display:flex;flex-direction:column;align-items:center;gap:14px;width:100%}
.hero-lead{margin:0;font-size:1.4rem;font-weight:800;line-height:1.55}
.hero-desc{margin:0;color:var(--sub)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;width:100%;max-width:640px;margin:0;padding:0;list-style:none}
.stat{background:#fff;border:2px solid var(--brand-soft);border-radius:14px;padding:10px 12px;text-align:center}
.stat .k{display:block;font-size:.85rem;font-weight:700;color:var(--sub)}
.stat .v{display:block;font-size:1.2rem;font-weight:800;line-height:1.45;color:var(--brand-deep)}
.stat .v b{font-size:1.9rem}
.stat .s{display:block;font-size:.8rem;color:var(--sub)}
.hero-btns{display:grid;grid-template-columns:minmax(0,1fr);gap:10px;width:100%;max-width:640px}
@media (min-width:560px){.hero-btns{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (min-width:880px){
  .hero{padding:32px 0 40px}
  .hero-grid{grid-template-columns:minmax(0,1fr) 330px;grid-template-areas:"title illust" "text illust";column-gap:48px;justify-items:start;text-align:left}
  .hero h1{grid-area:title;align-self:end;font-size:3rem}
  .hero-illust{grid-area:illust;width:100%;align-self:center}
  .hero-text{grid-area:text;align-items:flex-start;align-self:start}
}

/* さがす */
.search-area{padding:8px 0 36px}
.panel{background:var(--brand-pale);border:2px solid var(--brand-soft);border-radius:22px;padding:18px 16px 20px;box-shadow:0 8px 24px rgba(117,72,163,.08)}
@media (min-width:768px){.panel{padding:24px 28px 26px}}
.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
.panel-head .section-h{margin:0}
.panel-head p{margin:6px 0 0;color:var(--sub)}
.panel-illust{flex:none;width:100px;height:auto}
@media (min-width:768px){.panel-illust{width:160px}}
.field{display:flex;flex-direction:column;gap:6px;min-width:0;margin-top:18px}
.field-label{font-weight:800}
.field-label small{font-weight:700;color:var(--sub);margin-left:6px}
.searchbox{display:flex;gap:8px}
.searchbox input{flex:1 1 auto;min-width:0}
.searchbox .btn{flex:none;padding-left:22px;padding-right:22px}
input[type=search],select{width:100%;min-height:var(--btn-h);padding:8px 14px;border:2px solid var(--field);border-radius:12px;background:#fff;color:var(--ink);font:inherit;font-size:1rem}
input[type=search]{background:#fff url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%237548a3' d='M10 3a7 7 0 0 1 5.6 11.2l5.1 5.1-1.4 1.4-5.1-5.1A7 7 0 1 1 10 3zm0 2a5 5 0 1 0 0 10 5 5 0 0 0 0-10z'/%3E%3C/svg%3E") no-repeat 12px center/22px;padding-left:42px}
select{appearance:none;-webkit-appearance:none;cursor:pointer;padding-right:42px;background:#fff url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%237548a3' d='M7 9l5 5 5-5z'/%3E%3C/svg%3E") no-repeat right 10px center/26px}
input[type=search]:focus,select:focus{border-color:var(--brand);outline:3px solid rgba(117,72,163,.28);outline-offset:0}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:4px 14px;border:2px solid var(--field);border-radius:999px;background:#fff;color:var(--ink);font:inherit;font-size:.95rem;font-weight:700;cursor:pointer}
.chip:hover{border-color:var(--brand)}
.chip .dot{width:.7em;height:.7em;border-radius:50%;flex:none}
.chip .n{font-size:.8em;color:var(--sub)}
.chip[aria-pressed="true"]{background:var(--brand);border-color:var(--brand);color:#fff}
.chip[aria-pressed="true"]::before{content:"✓"}
.chip[aria-pressed="true"] .n{color:var(--brand-soft)}
.chip[aria-pressed="true"] .dot{box-shadow:0 0 0 2px #fff}
.field-row{display:grid;grid-template-columns:minmax(0,1fr);gap:0 16px}
@media (min-width:768px){.field-row{grid-template-columns:repeat(3,minmax(0,1fr))}}
.panel-foot{display:flex;flex-direction:column;gap:12px;margin-top:22px;padding-top:18px;border-top:2px dashed var(--brand-soft)}
.hit{margin:0;text-align:center;font-size:1.05rem;font-weight:700}
.hit b{font-size:1.7rem;color:var(--brand-deep)}
.panel-btns{display:grid;grid-template-columns:minmax(0,1fr);gap:10px}
@media (min-width:560px){.panel-btns{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (min-width:880px){.panel-foot{flex-direction:row;align-items:center;justify-content:space-between}.panel-btns{display:flex}}

/* 一覧 */
.results{padding:8px 0 48px}
.resultbar{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;gap:10px;margin:10px 0 12px;padding:8px 0;
  background:rgba(255,255,255,.97);border-bottom:2px solid var(--brand-soft)}
.resultbar p{margin:0;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-weight:700}
.resultbar b{font-size:1.35rem;color:var(--brand-deep)}
.rcond{color:var(--sub)}
.resultbar .btn{flex:none;min-height:44px;padding:4px 14px;font-size:.9rem}
.active{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 10px}
.active .chip{background:var(--brand-pale);border-color:var(--brand-line)}
.active .chip span{color:var(--brand-dark);font-size:.85em}
.linkbtn{min-height:44px;padding:0 6px;border:0;background:none;color:var(--brand-dark);font:inherit;font-weight:700;text-decoration:underline;cursor:pointer}
.sortnote{margin:0 0 14px;font-size:.9rem;color:var(--sub)}
.banner{max-width:440px;margin:0 auto 18px}
.banner img{display:block;width:100%;border:1px solid var(--line);border-radius:16px}
.cards{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;margin:0;padding:0;list-style:none}
@media (min-width:880px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
/* カードはどれも同じ白いカード。おすすめ・署名済みは、上のバッジだけで見分ける（黄色はおすすめバッジだけ） */
.card{display:flex;flex-direction:column;gap:12px;min-width:0;background:#fff;border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px 18px;box-shadow:0 2px 10px rgba(15,23,42,.05)}
.card-title{margin:0;font-size:1.2rem;font-weight:800;line-height:1.5;overflow-wrap:anywhere}
.card-title a{color:var(--ink);text-decoration:none}
.card-title a:hover{color:var(--brand-deep);text-decoration:underline}
.card-summary{margin:0;font-size:.95rem;line-height:1.7;color:#374151;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.card-summary .lbl{display:inline-block;margin-right:6px;padding:0 7px;border-radius:6px;background:var(--brand-pale);color:var(--brand-dark);font-size:.8rem;font-weight:800}
.facts{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:6px 14px;margin:0;padding:12px 14px;border-radius:12px;background:var(--bg-soft);font-size:.95rem}
.facts dt{font-size:.88rem;font-weight:800;color:var(--sub);line-height:1.9}
.facts dd{margin:0;min-width:0;overflow-wrap:anywhere}
.facts .num{font-size:1.3rem;font-weight:800;color:var(--brand-deep)}
.facts .when{font-size:.85rem;color:var(--sub)}
.clamp2{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card-actions{display:flex;flex-direction:column;gap:10px;margin-top:auto}
.empty{grid-column:1/-1;padding:24px 16px 30px;border-radius:var(--radius);background:var(--bg-soft);text-align:center}
.empty img{width:170px}
.empty-h{margin:8px 0 4px;font-size:1.25rem;font-weight:800;color:var(--brand-deep)}
.empty p{margin:0 0 14px}

/* はじめての方へ */
.steps{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;margin:0;padding:0;list-style:none}
@media (min-width:768px){.steps{grid-template-columns:repeat(3,minmax(0,1fr))}}
.step{position:relative;display:flex;flex-direction:column;align-items:center;background:var(--brand-pale);border:2px solid var(--brand-soft);border-radius:22px;padding:18px 18px 20px}
.step-n{position:absolute;left:14px;top:14px;display:flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:50%;background:var(--brand);color:#fff;font-size:1.25rem;font-weight:800}
.step img{display:block;height:140px;width:auto;max-width:100%;object-fit:contain;margin:6px 0 10px}
.step h3{margin:0 0 6px;font-size:1.2rem;color:var(--brand-deep);text-align:center}
.step p{margin:0;align-self:stretch}
.tip{display:flex;align-items:center;gap:16px;margin-top:18px;padding:16px 18px;border-radius:20px;background:var(--brand-pale);border:2px dashed var(--brand-line)}
.tip img{flex:none;width:110px}
.tip p{margin:0}
@media (max-width:520px){.tip{flex-direction:column}}

/* 注意事項 */
.notes-main{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;align-items:center;margin-bottom:12px}
.notes-main>img{display:block;width:150px;margin:0 auto}
@media (min-width:768px){.notes-main{grid-template-columns:200px minmax(0,1fr)}.notes-main>img{width:190px}}

/* 署名サイトの違い（まとめ） */
.site-cards{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;margin:0 0 18px}
@media (min-width:768px){.site-cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
.site-card{border:2px solid;border-radius:16px;padding:14px 18px}
.site-card.voice{background:#fff5f7;border-color:#fecdd3}
.site-card.change{background:#fffbea;border-color:#fde68a}
.site-card h3{margin:0 0 4px;font-size:1.15rem}
.site-card ul{margin:0;padding-left:1.2em}

/* ===== まとめページ・説明ページ ===== */
.page{max-width:900px;padding-top:8px;padding-bottom:40px}
.back{display:inline-flex;align-items:center;min-height:44px;font-weight:700}
.page-title{margin:8px 0 14px;font-size:1.5rem;line-height:1.5;overflow-wrap:anywhere}
@media (min-width:768px){.page-title{font-size:1.75rem}}
.detail-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;align-items:start}
@media (max-width:767px){.detail-grid .side{order:-1}}
@media (min-width:768px){.detail-grid{grid-template-columns:minmax(0,1.15fr) minmax(0,1fr)}}
.shot{display:block;width:100%;border:1px solid var(--line);border-radius:14px}
.side{display:flex;flex-direction:column;gap:10px}
.countbox{padding:14px 16px;border-radius:16px;background:var(--brand-pale)}
.countbox .k{display:block;font-size:.88rem;font-weight:800;color:var(--sub)}
.countbox .num{font-size:2.1rem;font-weight:800;color:var(--brand-deep)}
.countbox .when{display:block;font-size:.85rem;color:var(--sub)}
.page .box{margin:16px 0}
.facts.plain{background:none;padding:0}
.notice-box{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;align-items:center;background:var(--brand-pale);border-color:var(--brand-soft)}
.notice-box>img{width:120px;margin:0 auto}
@media (min-width:600px){.notice-box{grid-template-columns:130px minmax(0,1fr)}.notice-box>img{width:130px}}
.chart{display:block;width:100%;height:auto}
.chart polyline{fill:none;stroke:var(--brand);stroke-width:3}
.chart circle{fill:var(--brand)}
.chart text{fill:var(--sub);font-size:13px}
.chart .axis{stroke:var(--line)}
.page-intro{display:grid;grid-template-columns:minmax(0,1fr);gap:8px;align-items:center}
.page-intro>img{width:150px;margin:0 auto}
@media (min-width:768px){.page-intro{grid-template-columns:minmax(0,1fr) 180px}.page-intro>img{width:180px}}
"""

CSS_VER = hashlib.md5(BASE_CSS.encode("utf-8")).hexdigest()[:8]


def write_css():
    (OUT_DIR / "style.css").write_text(BASE_CSS.lstrip(), encoding="utf-8")


SUMMARY_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__｜__SITE_NAME__</title>
<meta name="description" content="__DESC__">
<meta property="og:type" content="article">
<meta property="og:title" content="【署名】__TITLE__">
<meta property="og:description" content="__DESC__">
<meta property="og:url" content="__PAGE_URL__">
__OG_IMAGE__
<meta name="twitter:card" content="__CARD__">
__HEAD__
</head>
<body id="top">
__TOPBAR__
<main class="wrap page">
<a class="back" href="../">← 署名の一覧にもどる</a>
<div class="badges"><span class="badge signed" id="signedmark" hidden>✅ 署名済み</span>__PICK__<span class="badge left" id="left" hidden></span>__TAGS____PREF____SITEBADGE__</div>
<h1 class="page-title">__TITLE__</h1>

<div class="detail-grid">
  <div>__IMG__</div>
  <div class="side">
    __COUNTBOX__
    <a class="btn btn-primary btn-cta btn-block" href="__URL__" target="_blank" rel="noopener" aria-label="署名ページを見る（__SITE__・外部サイトが新しいタブで開きます）">署名ページを見る__EXT_ICON__</a>
    <p class="ext-note">__SITE__（外部サイト）が新しいタブで開きます</p>
    <div class="btn-row">
      <button type="button" class="btn btn-sub" id="signed" aria-pressed="false">☐ 署名した</button>
      <button type="button" class="btn btn-sub" id="share">𝕏 シェア</button>
    </div>
    <p class="note">「署名した」を押すと、この端末のブラウザの中にだけ記録されます。</p>
  </div>
</div>

<section class="box notice-box" aria-labelledby="notice-h">
  __PLEASE_IMG__
  <div>
    <h2 id="notice-h">署名する前に、確認してね</h2>
    <ul class="checklist">
      <li><b>発起人と内容を確認してから</b>下の「どんな署名？」と「基本情報」の発起人を、必ず確認してから署名してください。</li>
      __CHANGE_NOTE__
      <li><b>掲載＝賛成・保証ではありません</b>この掲示板に載っていても、署名の内容に賛成・保証するものではありません。</li>
      <li><b>支援金（お金）は任意です</b>署名のあとにお金の画面が出ても、払わずに署名だけで参加できます。くわしくは<a href="../sites.html">署名サイトの違い</a>へ。</li>
    </ul>
  </div>
</section>

<section class="box">
  <h2>📝 どんな署名？</h2>
  <p>__SUMMARY__</p>
  <p class="note">※ 署名ページの本文の書き出しです。全文は署名ページでご確認ください。</p>
</section>

<section class="box">
  <h2>📋 基本情報</h2>
  <dl class="facts plain">__FACTS__</dl>
</section>

<section class="box">
  <h2>📈 署名数の推移</h2>
  __CHART__
  <p class="note">署名数は当サイトが確認した日の人数です。最新の人数は署名ページでご確認ください。</p>
</section>

<a class="btn btn-primary btn-cta btn-block" href="__URL__" target="_blank" rel="noopener" aria-label="署名ページを見る（__SITE__・外部サイトが新しいタブで開きます）">署名ページを見る__EXT_ICON__</a>
<p class="ext-note">__SITE__（外部サイト）が新しいタブで開きます</p>
<p style="text-align:center;margin-top:20px"><a class="btn btn-sub" href="../">← 署名の一覧にもどる</a></p>
</main>
__FOOTER__
<script>
__COMMON_JS__
__SHARE_JS__
const end = '__END_ISO__';
if (end) {
  const ymd = d => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  const dl = Math.round((Date.UTC(...end.split('-').map((v, i) => i === 1 ? v - 1 : +v)) - ymd(new Date())) / 86400000);
  const left = document.getElementById('left');
  left.hidden = false;
  left.textContent = '⏰ ' + (dl < 0 ? '終了' : dl === 0 ? '本日終了' : `あと${dl}日`);
  if (dl <= __URGENT_DAYS__) left.classList.add('urgent');
}
document.getElementById('share').onclick = () => shareX(__SHARE__);
__SIGNED_JS__
const ID = __ID__;
const sb = document.getElementById('signed');
const paint = () => {
  const on = !!loadSigned()[ID];
  sb.setAttribute('aria-pressed', on);
  sb.textContent = on ? '✅ 署名済み（押すと取り消し）' : '☐ 署名した';
  document.getElementById('signedmark').hidden = !on;
};
sb.onclick = () => { toast(toggleSigned(ID) ? '✅ 署名済みにしました。ありがとう！' : '署名済みを取り消しました'); paint(); };
paint();
</script>
</body>
</html>
"""


TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__SITE_NAME__｜いま賛同を集めている署名の一覧</title>
<meta name="description" content="__SITE_DESC__">
<meta property="og:type" content="website">
<meta property="og:title" content="__SITE_NAME__｜いま集まっている署名 __COUNT__件">
<meta property="og:description" content="__SITE_DESC__">
<meta property="og:url" content="__SITE_URL__">
__OG_IMAGE__
<meta name="twitter:card" content="summary_large_image">
__HEAD__
</head>
<body id="top">
__TOPBAR__
<main>
<!-- ①タイトル ②しょめたん ③説明 ④件数・最終更新日 -->
<section class="hero">
  <div class="wrap hero-grid">
    <h1>__SITE_NAME__</h1>
    <figure class="hero-illust">__HERO_IMG__</figure>
    <div class="hero-text">
      <p class="hero-lead"><span class="nw">気になる署名を探して、</span><span class="nw">あなたの声を届けよう</span></p>
      <p class="hero-desc">__SITE_DESC__</p>
      <ul class="stats">
        <li class="stat"><span class="k">掲載中の署名</span><span class="v"><b>__COUNT__</b> 件</span></li>
        <li class="stat"><span class="k">最終更新日</span><span class="v">__UPDATED_JP__</span><span class="s">__UPDATE_NOTE__</span></li>
        <li class="stat" id="mineStat" hidden><span class="k">あなたが署名した</span><span class="v"><b id="mineN">0</b> 件</span><span class="s">この端末の記録</span></li>
      </ul>
      <div class="hero-btns">
        <a class="btn btn-primary" href="#search">署名をさがす</a>
        <a class="btn btn-sub" href="#howto">はじめての方へ</a>
      </div>
    </div>
  </div>
</section>

<!-- ⑤キーワード検索 ⑥テーマ別・地域別の絞り込み -->
<section class="search-area" aria-labelledby="search-h">
  <div class="wrap">
  <div class="panel" id="search">
    <div class="panel-head">
      <div>
        <h2 class="section-h" id="search-h">署名をさがす</h2>
        <p>キーワード・テーマ・地域を組み合わせて探せます。</p>
      </div>
      __IMG_SEARCH__
    </div>
    <div class="field">
      <label class="field-label" for="q">キーワード</label>
      <div class="searchbox">
        <input id="q" type="search" placeholder="例：大阪、墓地" autocomplete="off" enterkeyhint="search">
        <button type="button" class="btn btn-primary" id="go">探す</button>
      </div>
    </div>
    <div class="field" role="group" aria-labelledby="tag-l">
      <span class="field-label" id="tag-l">テーマ<small>1つ選べます</small></span>
      <div class="chips" id="tagbar"></div>
    </div>
    <div class="field-row">
      <div class="field"><label class="field-label" for="pref">地域（都道府県）</label><select id="pref"></select></div>
      <div class="field"><label class="field-label" for="sort">並び順</label>
        <select id="sort">
          <option value="new">新着順</option>
          <option value="count">署名が多い順</option>
          <option value="rate">最近伸びている順</option>
          <option value="end">終了日が近い順</option>
        </select></div>
      <div class="field"><label class="field-label" for="signedSel">署名済み（✅）の署名</label>
        <select id="signedSel">
          <option value="all">表示する</option>
          <option value="hide">隠す</option>
          <option value="only">署名済みだけ表示</option>
        </select></div>
    </div>
    <div class="panel-foot">
      <p class="hit" id="hit" aria-live="polite"></p>
      <div class="panel-btns">
        <button type="button" class="btn btn-sub" id="clear">条件をクリア</button>
        <a class="btn btn-primary" href="#results">結果を見る ↓</a>
      </div>
    </div>
  </div>
  </div>
</section>

<!-- ⑦署名一覧 -->
<section class="results" aria-labelledby="results-h">
  <div class="wrap">
    <h2 class="section-h" id="results-h">署名の一覧</h2>
    <div class="resultbar" id="results">
      <p><b id="rcount">0</b>件を表示中 <span class="rcond" id="rcond"></span></p>
      <a class="btn btn-sub" href="#search">条件を変える</a>
    </div>
    <div class="active" id="active" hidden></div>
    <p class="sortnote" id="sortnote"></p>
    <figure class="banner" id="banner" hidden><img id="bannerImg" src="data:," alt="" width="800" height="533"></figure>
    <ul class="cards" id="list"></ul>
  </div>
</section>

<!-- はじめての方へ -->
<section class="section" id="howto" aria-labelledby="howto-h">
  <div class="wrap">
    <h2 class="section-h" id="howto-h">署名ってどうするの？</h2>
    <p class="section-lead">はじめての方へ。ネットの署名は、3つのステップで参加できます。</p>
    <ol class="steps">
      <li class="step"><span class="step-n" aria-hidden="true">1</span>__IMG_STEP1__
        <h3>気になる署名を探す</h3>
        <p>上の<a href="#search">「署名をさがす」</a>で、キーワード・テーマ・地域を組み合わせて探せます。</p></li>
      <li class="step"><span class="step-n" aria-hidden="true">2</span>__IMG_STEP2__
        <h3>内容と発起人を確認する</h3>
        <p>カードの「くわしく見る」や署名ページで、何を求める署名か、だれが始めたか（発起人）を確かめます。</p></li>
      <li class="step"><span class="step-n" aria-hidden="true">3</span>__IMG_STEP3__
        <h3>署名サイトで賛同する</h3>
        <p>紫色の「署名ページを見る」を押すと、署名サイト（Voice または change.org）が開きます。内容に賛成できたら、そのサイトで署名します。</p></li>
    </ol>
    <div class="tip">__IMG_THANKS__
      <p><b>署名したら「☐ 署名した」を押しておこう。</b>カードに ✅ がついて、どれに署名したかがひと目でわかります。「署名済み（✅）の署名」で、隠したり、それだけ表示したりもできます。記録はこの端末のブラウザの中だけに残り、どこにも送られません。</p>
    </div>
  </div>
</section>

<!-- ⑧注意事項・署名サイトの違い -->
<section class="section" id="notes" aria-labelledby="notes-h">
  <div class="wrap">
    <h2 class="section-h" id="notes-h">署名する前に確認してほしいこと</h2>
    <div class="notes-main">
      __IMG_PLEASE__
      <ul class="checklist">
        <li><b>掲載＝賛成・保証ではありません</b>この掲示板に載っていても、署名の内容に賛成したり、保証したりするものではありません。</li>
        <li><b>発起人と内容を確かめてから署名を</b>だれが、何を求めて始めた署名なのかを確認してから、ご自身で判断してください。</li>
        <li><b>署名数は「確認した日」の人数です</b>カードに確認した日を書いています。最新の人数は署名ページでご確認ください。</li>
        <li><b>支援金（お金）は任意です</b>署名のあとに「お金で応援しませんか」という画面が出ることがありますが、払わなくても署名だけで参加できます。</li>
      </ul>
    </div>
    <details>
      <summary>この掲示板にのせている署名について</summary>
      <div>
        <p>このページでは、change.org と Voice の2つの署名サイトをキーワードで検索し、その中から運営者が選んだ署名を載せています。内容を保証するものではありません。</p>
        <p>change.org の署名については、内容をよく確かめたうえで、ご自身で判断してください。</p>
        <p>カードの「概要」は、署名ページの本文の書き出しです。全文は署名ページでご確認ください。</p>
      </div>
    </details>
    <details>
      <summary>支援金（お金での応援）について</summary>
      <div>
        <p>どちらのサイトも、署名のあとに「お金で応援しませんか」という画面が出ることがあります。<b>お金を払わなくても、署名だけで参加できます。</b>支払い画面が出ても、そのまま閉じてかまいません。</p>
        <ul>
          <li>Voice の「エール」は、署名を始めた人（発起人）に届きます（手数料を引いた額）。</li>
          <li>change.org の支援金は、発起人ではなく change.org（運営会社）に支払われます。</li>
        </ul>
        <p>くわしくは <a href="sites.html">署名サイトの違い</a> をご覧ください。</p>
      </div>
    </details>
    <details>
      <summary>「署名した」の記録について</summary>
      <div>
        <p>「☐ 署名した」を押すと、この端末のブラウザの中だけに記録されます（どこにも送られません）。</p>
        <p>別の端末や、閲覧履歴を消したあとには引き継がれません。</p>
      </div>
    </details>

    <h2 class="section-h" id="sites" style="margin-top:40px">署名サイトの違い（Voice と change.org）</h2>
    <p class="section-lead">この掲示板の署名は、Voice と change.org の2つのサイトのものです。運営している会社や、支援金の行き先がちがいます。</p>
    <div class="site-cards">
      <div class="site-card voice"><h3>📣 Voice</h3><ul><li>運営：Voice株式会社（日本の会社）</li><li>支援金（エール）は、発起人に届きます</li></ul></div>
      <div class="site-card change"><h3>🌐 change.org</h3><ul><li>運営：Change.org, Inc.（アメリカの会社）</li><li>支援金は、運営会社（change.org）に支払われます</li></ul></div>
    </div>
    <a class="btn btn-primary" href="sites.html">2つのサイトの違いをくわしく見る →</a>
  </div>
</section>
</main>
__FOOTER__

<script id="data" type="application/json">__DATA__</script>
<script>
__COMMON_JS__
__SIGNED_JS__
__SHARE_JS__
const D = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
const tagColor = Object.fromEntries(D.tags.map(t => [t.name, t.color]));
const charaOf = Object.fromEntries(D.tags.map(t => [t.name, t.chara]));
const PICK = '__pick__', NONE = '__none__';
const EXT = '__EXT_ICON__';
const SORTS = { new: '新着順', count: '署名が多い順', rate: '最近伸びている順', end: '終了日が近い順' };
const DEFAULT = { q: '', tag: '', pref: '', sort: 'new', signed: 'all' };
const state = { ...DEFAULT };

function esc(s){ return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
const norm = s => String(s ?? '').normalize('NFKC').toLowerCase();
const num = n => n.toLocaleString();
function ymd(d){ return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()); }
function daysLeft(iso){ const [y,m,d] = iso.split('-').map(Number); return Math.round((Date.UTC(y, m-1, d) - ymd(new Date())) / 86400000); }
function mdJp(iso){ const [, m, d] = iso.split('-').map(Number); return `${m}月${d}日`; }
function ymdJp(iso){ const [y, m, d] = iso.split('-').map(Number); return `${y}年${m}月${d}日`; }
const siteName = i => i.site === 'Change' ? 'change.org' : 'Voice';
// キーワードは、タイトル・概要・発起人・提出先・地域・テーマ・サイト名から探す（全角半角・大文字小文字は区別しない）
D.items.forEach(i => { i.text = norm([i.title, i.summary, i.starter, i.target, i.pref, ...i.tags, siteName(i)].join(' ')); });

// テーマのボタン
const chips = [{ name: '', label: 'すべて', n: D.items.length },
               { name: PICK, label: '⭐ おすすめ', n: D.items.filter(i => i.pick).length },
               ...D.tags.map(t => ({ name: t.name, label: t.name, color: t.color, n: D.items.filter(i => i.tags.includes(t.name)).length }))]
  .filter(t => t.name === '' || t.n);
const tagbar = $('tagbar');
tagbar.innerHTML = chips.map(t => `<button type="button" class="chip" data-tag="${esc(t.name)}" aria-pressed="false">`
  + (t.color ? `<span class="dot" style="background:${t.color}"></span>` : '') + `${esc(t.label)}<span class="n">${t.n}件</span></button>`).join('');

// 地域：北から順に、地方ごとにまとめる
const AREAS = [['北海道・東北', 7], ['関東', 7], ['中部', 9], ['近畿', 7], ['中国', 5], ['四国', 4], ['九州・沖縄', 8]];
const prefIndex = p => D.prefs.indexOf(p.replace(/[都府県]$/, ''));
const prefCount = {};
D.items.forEach(i => { const k = i.pref || NONE; prefCount[k] = (prefCount[k] || 0) + 1; });
const prefSel = $('pref');
prefSel.add(new Option(`すべての地域（${D.items.length}件）`, ''));
let from = 0;
for (const [area, n] of AREAS) {
  const names = Object.keys(prefCount).filter(p => p !== NONE && prefIndex(p) >= from && prefIndex(p) < from + n).sort((a, b) => prefIndex(a) - prefIndex(b));
  from += n;
  if (!names.length) continue;
  const g = document.createElement('optgroup'); g.label = area;
  names.forEach(p => g.appendChild(new Option(`${p}（${prefCount[p]}件）`, p)));
  prefSel.appendChild(g);
}
const others = Object.keys(prefCount).filter(p => p !== NONE && prefIndex(p) < 0);
if (others.length || prefCount[NONE]) {
  const g = document.createElement('optgroup'); g.label = 'そのほか';
  others.forEach(p => g.appendChild(new Option(`${p}（${prefCount[p]}件）`, p)));
  if (prefCount[NONE]) g.appendChild(new Option(`地域の記載がない署名（${prefCount[NONE]}件）`, NONE));
  prefSel.appendChild(g);
}

// アドレスに残した条件を読む（戻るボタンや再読みこみで、条件が消えないように）
const P = new URLSearchParams(location.search);
for (const k of Object.keys(state)) if (P.get(k)) state[k] = P.get(k);
if (!chips.some(t => t.name === state.tag)) state.tag = '';
// 地域は「東京都」のような正式名も受け付ける。掲載中の署名が0件の県や、都道府県でない名前でも、
// 指定を外して全件を出すことはせず、その地域を選んだまま0件と理由を示す
const hasPref = p => [...prefSel.options].some(o => o.value === p);
const fullPref = p => p === '北海道' ? p : p + (p === '東京' ? '都' : p === '京都' || p === '大阪' ? '府' : '県');
if (state.pref && !hasPref(state.pref)) {
  const p = state.pref.normalize('NFKC').trim();
  const short = [p, p.replace(/[都府県]$/, '')].find(x => D.prefs.includes(x));
  state.pref = short || p;
  if (state.pref && !hasPref(state.pref)) prefSel.insertBefore(new Option(short ? `${fullPref(short)}（0件）` : `${p}（対象外）`, state.pref), prefSel.children[1] || null);
}
if (!SORTS[state.sort]) state.sort = 'new';
if (!['all', 'hide', 'only'].includes(state.signed)) state.signed = 'all';
function syncControls(){
  $('q').value = state.q; prefSel.value = state.pref; $('sort').value = state.sort; $('signedSel').value = state.signed;
}

const sorters = {
  count: (a, b) => (b.count || 0) - (a.count || 0),
  rate:  (a, b) => (b.rate || 0) - (a.rate || 0),
  end:   (a, b) => (a.end || '9999') < (b.end || '9999') ? -1 : (a.end || '9999') > (b.end || '9999') ? 1 : 0,
  // 新着順：このサイトに加わった日が新しい順 → 同じ日なら開始日が新しい順（開始日がわからないものは後ろ）
  new:   (a, b) => (b.found || '').localeCompare(a.found || '') || (b.start || '').localeCompare(a.start || ''),
};

// いま選んでいる条件（表示用）
function conditions(){
  const c = [];
  if (state.q) c.push({ key: 'q', label: `キーワード「${state.q}」`, short: `「${state.q}」` });
  if (state.tag) c.push({ key: 'tag', label: state.tag === PICK ? '⭐ おすすめ' : `テーマ：${state.tag}`, short: state.tag === PICK ? 'おすすめ' : state.tag });
  if (state.pref) c.push({ key: 'pref', label: `地域：${state.pref === NONE ? '記載なし' : state.pref}`, short: state.pref === NONE ? '地域の記載なし' : state.pref });
  if (state.signed !== 'all') c.push({ key: 'signed', label: state.signed === 'hide' ? '署名済みを隠す' : '署名済みだけ', short: state.signed === 'hide' ? '署名済みを隠す' : '署名済みだけ' });
  return c;
}

function card(i, done){
  const site = siteName(i);
  let left = '';
  if (i.end) {
    const dl = daysLeft(i.end);
    left = `<span class="badge left${dl <= D.urgentDays ? ' urgent' : ''}">⏰ ${dl <= 0 ? '本日終了' : `あと${dl}日`}</span>`;
  }
  const badges = [done && '<span class="badge signed">✅ 署名済み</span>', i.pick && '<span class="badge pick">⭐ おすすめ</span>', left].filter(Boolean).join('');
  const facts = [
    ['テーマ', `<span class="badges">${i.tags.map(t => `<span class="badge"><span class="dot" style="background:${tagColor[t]}"></span>${esc(t)}</span>`).join('')}</span>`],
    i.pref && ['地域', `📍 ${esc(i.pref)}`],
    ['掲載元', `<span class="badge ${i.site === 'Change' ? 'change' : 'voice'}">${site}</span>`],
    i.count != null && ['署名数', `<span class="num">${num(i.count)}</span> 人 <span class="when">（${ymdJp(i.countDate)} 確認）</span>`
      + (i.grow > 0 ? `<span class="grow">↑ 前回（${mdJp(i.growFrom)}）から +${num(i.grow)}人</span>` : '')],
    i.starter && ['発起人', `<span class="clamp2">${esc(i.starter)}</span>`],
    i.target && ['提出先', `<span class="clamp2">${esc(i.target)}</span>`],
    (i.start || i.end) && ['期間', [i.start && `${ymdJp(i.start)} 開始`, i.end && `${ymdJp(i.end)} 終了`].filter(Boolean).join('<br>')],
  ].filter(Boolean).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
  return `<li class="card">
    ${badges ? `<div class="badges">${badges}</div>` : ''}
    <h3 class="card-title"><a href="${esc(i.page)}">${esc(i.title)}</a></h3>
    ${i.summary ? `<p class="card-summary"><span class="lbl">概要</span>${esc(i.summary)}</p>` : ''}
    <dl class="facts">${facts}</dl>
    <div class="card-actions">
      <a class="btn btn-primary btn-cta btn-block" href="${esc(i.url)}" target="_blank" rel="noopener" aria-label="署名ページを見る（${site}・外部サイトが新しいタブで開きます）">署名ページを見る${EXT}</a>
      <p class="ext-note">${site}（外部サイト）が開きます</p>
      <div class="btn-row">
        <button type="button" class="btn btn-sub" data-signed="${esc(i.id)}" aria-pressed="${done}">${done ? '✅ 署名済み' : '☐ 署名した'}</button>
        <a class="btn btn-sub" href="${esc(i.page)}">くわしく見る</a>
        <button type="button" class="btn btn-sub" data-share="${esc(i.id)}">𝕏 シェア</button>
      </div>
    </div>
  </li>`;
}

function empty(signed){
  // 指定された地域に、掲載中の署名が1件もないとき
  if (state.pref && state.pref !== NONE && !prefCount[state.pref]) {
    const known = D.prefs.includes(state.pref);
    return `<li class="empty"><img src="${D.oops.src}" alt="「あれっ？」とおどろく、しょめたん" width="${D.oops.w}" height="${D.oops.h}">
    <p class="empty-h">${known ? `${esc(fullPref(state.pref))}に関係する掲載中の署名は0件です` : `「${esc(state.pref)}」は収集の対象外です`}</p>
    <p>${known ? '地域は、署名のタイトルと提出先に書かれた都道府県で分けています。地域が書かれていない署名（全国向けなど）は「すべての地域」で見られます。'
               : 'この掲示板の地域は、47都道府県です（市区町村ごとには分けていません）。「東京都」のように、都道府県の名前で指定してください。'}</p>
    <button type="button" class="btn btn-primary" data-clear="pref">すべての地域を見る</button></li>`;
  }
  const none = state.signed === 'only' && !D.items.some(i => signed[i.id]);
  return `<li class="empty"><img src="${D.oops.src}" alt="「あれっ？」とおどろく、しょめたん" width="${D.oops.w}" height="${D.oops.h}">
    <p class="empty-h">${none ? 'まだ「署名した」を押した署名はありません' : '条件に合う署名が見つかりませんでした'}</p>
    <p>${none ? '署名したあとにカードの「☐ 署名した」を押すと、ここに表示されます。' : 'キーワードを短くしたり、テーマや地域を「すべて」にしたりして、もう一度さがしてみてください。'}</p>
    <button type="button" class="btn btn-primary" data-clear="all">条件をクリアする</button></li>`;
}

function render(){
  const signed = loadSigned();
  const mine = D.items.filter(i => signed[i.id]).length;
  $('mineStat').hidden = !mine; $('mineN').textContent = mine;
  tagbar.querySelectorAll('.chip').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.tag === state.tag)));
  const words = norm(state.q).split(/\s+/).filter(Boolean);
  const items = D.items.filter(i =>
    (!state.tag || (state.tag === PICK ? i.pick : i.tags.includes(state.tag))) &&
    (!state.pref || (state.pref === NONE ? !i.pref : i.pref === state.pref)) &&
    (state.signed !== 'hide' || !signed[i.id]) &&
    (state.signed !== 'only' || signed[i.id]) &&
    words.every(w => i.text.includes(w))
  // おすすめはいつも先頭（おすすめどうしは、選別画面で決めた順位の順）
  ).sort((a, b) => (b.pick - a.pick) || (a.pick && b.pick ? a.rank - b.rank : 0) || sorters[state.sort](a, b));

  const conds = conditions();
  $('hit').innerHTML = `全${D.items.length}件のうち <b>${items.length}</b> 件が見つかりました`;
  $('rcount').textContent = items.length;
  $('rcond').textContent = conds.length ? `（${conds.map(c => c.short).join('・')}）` : '（すべての署名）';
  $('active').hidden = !conds.length;
  $('active').innerHTML = conds.map(c => `<button type="button" class="chip" data-clear="${c.key}" aria-label="${esc(c.label)} の条件を外す">${esc(c.label)}<span aria-hidden="true">✕</span></button>`).join('')
    + (conds.length > 1 ? '<button type="button" class="linkbtn" data-clear="all">すべてクリア</button>' : '');
  $('clear').disabled = !conds.length;
  $('sortnote').textContent = `並び順：⭐おすすめを先頭に、${SORTS[state.sort]}`;

  // テーマを選んだときは、そのテーマのしょめたんの絵を出す（テーマ専用の絵がなければ共通の絵）
  const src = state.tag === PICK ? D.charaPick : state.tag ? (charaOf[state.tag] || D.charaAll) : '';
  const banner = $('banner'), bimg = $('bannerImg');
  banner.hidden = !src;
  if (src) {
    if (bimg.getAttribute('src') !== src) bimg.src = src;
    bimg.alt = state.tag === PICK ? 'しょめたんのイラスト（おすすめの署名）' : `しょめたんのイラスト（「${state.tag}」の署名）`;
  }

  $('list').innerHTML = items.length ? items.map(i => card(i, !!signed[i.id])).join('') : empty(signed);

  const p = new URLSearchParams();
  for (const k of Object.keys(state)) if (state[k] !== DEFAULT[k]) p.set(k, state[k]);
  const qs = p.toString();
  try { history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash); } catch (e) {}
}

function clearAll(){ Object.assign(state, { q: '', tag: '', pref: '', signed: 'all' }); syncControls(); render(); }
function showResults(){ $('q').blur(); $('results').scrollIntoView(); }

$('q').addEventListener('input', e => { state.q = e.target.value.trim(); render(); });
$('q').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); showResults(); } });
$('go').onclick = showResults;
tagbar.addEventListener('click', e => { const b = e.target.closest('.chip'); if (!b) return; state.tag = b.dataset.tag; render(); });
prefSel.onchange = e => { state.pref = e.target.value; render(); };
$('sort').onchange = e => { state.sort = e.target.value; render(); };
$('signedSel').onchange = e => { state.signed = e.target.value; render(); };
$('clear').onclick = clearAll;
function onClear(e){
  const c = e.target.closest('[data-clear]'); if (!c) return false;
  if (c.dataset.clear === 'all') clearAll();
  else { state[c.dataset.clear] = DEFAULT[c.dataset.clear]; syncControls(); render(); }
  return true;
}
$('active').addEventListener('click', onClear);
$('list').addEventListener('click', e => {
  if (onClear(e)) return;
  const s = e.target.closest('button[data-signed]');
  if (s) { toast(toggleSigned(s.dataset.signed) ? '✅ 署名済みにしました。ありがとう！' : '署名済みを取り消しました'); render(); return; }
  const x = e.target.closest('button[data-share]');
  if (x) shareX(D.items.find(i => i.id === x.dataset.share).share);
});
// ほかのタブで「署名した」を押したときも、表示をそろえる
addEventListener('storage', e => { if (e.key === SIGNED_KEY) render(); });
syncControls();
render();
</script>
</body>
</html>
"""

SITES_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>署名サイトの違い（Voice と change.org）｜__SITE_NAME__</title>
<meta name="description" content="署名サイト Voice と change.org の違い（運営会社・特徴・支援金の使われ方）をわかりやすく整理しました。">
<meta property="og:type" content="article">
<meta property="og:title" content="署名サイトの違い（Voice と change.org）">
<meta property="og:description" content="Voice と change.org の違いを、運営会社・特徴・支援金の使われ方で比べました。">
<meta property="og:url" content="__SITE_URL__sites.html">
<meta property="og:image" content="__SITE_URL__sites-compare.webp">
<meta name="twitter:card" content="summary_large_image">
__HEAD__
<style>
:root{--voice:#e11d48;--voice-bg:#fff1f3;--change:#ca8a04;--change-bg:#fffbea}
.lead{margin:0 0 6px}
.asof{color:var(--sub);font-size:.85rem;margin:0}
.page h2.section-h{margin-top:36px}
.cols{display:grid;grid-template-columns:minmax(0,1fr);gap:14px}
@media (min-width:640px){.cols{grid-template-columns:repeat(2,minmax(0,1fr))}}
.site{background:#fff;border:1px solid var(--line);border-radius:16px;overflow:hidden}
.site h3{margin:0;padding:10px 16px;font-size:1.15rem;color:#fff}
.site h3 small{display:block;font-size:.85rem;font-weight:400;opacity:.95}
.site.voice h3{background:var(--voice)}
.site.change h3{background:var(--change);color:#1c1b19}
.site dl{margin:0;padding:6px 16px 14px}
.site dt{font-size:.85rem;font-weight:700;color:var(--sub);margin-top:8px}
.site dd{margin:0}
.site ul{margin:2px 0 0;padding-left:1.2em}
.pay{border-radius:16px;padding:14px 18px}
.pay.voice{background:var(--voice-bg);border:2px solid var(--voice)}
.pay.change{background:var(--change-bg);border:2px solid var(--change)}
.pay h3{margin:0 0 6px;font-size:1.1rem}
.pay ul{margin:0;padding-left:1.2em}
.pay li{margin:3px 0}
figure.zu{margin:18px 0 0}
figure.zu img{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:14px}
figure.zu figcaption{margin-top:4px;font-size:.85rem;color:var(--sub)}
</style>
</head>
<body id="top">
__TOPBAR__
<main class="wrap page">
<a class="back" href="./">← 署名の一覧にもどる</a>
<div class="page-intro">
  <div>
    <h1 class="page-title">署名サイトの違い</h1>
    <p class="lead">このページに載せている署名は、<b>Voice</b> と <b>change.org</b> の2つのサイトのものです。どちらも「ネットで署名を集めるサイト」ですが、運営している会社や、お金（支援金）の使われ方が違います。</p>
    <p class="asof">※2026年10月時点の、各サイトの公式情報をもとにまとめています。</p>
  </div>
  __CHECK_IMG__
</div>
<figure class="zu"><a href="sites-compare.webp" target="_blank" rel="noopener"><img src="sites-compare.webp" alt="Voice と change.org の比較図" width="1225" height="972"></a><figcaption>図を押すと大きく表示されます。下に同じ内容を文章でも書いています。</figcaption></figure>

<h2 class="section-h">ひと目でわかる違い</h2>
<div class="cols">
  <section class="site voice">
    <h3>📣 Voice<small>声で、社会を動かす。</small></h3>
    <dl>
      <dt>運営会社</dt><dd>Voice株式会社（日本の会社）</dd>
      <dt>本社</dt><dd>東京都渋谷区</dd>
      <dt>サービス開始</dt><dd>2020年</dd>
      <dt>主に使っている人</dt><dd>日本国内の個人・団体</dd>
      <dt>特徴</dt><dd><ul>
        <li>日本の社会の問題に特化</li>
        <li>署名だけでなく、意見の投稿もできる</li>
        <li>役所やメディアに届けた実績がある</li>
      </ul></dd>
    </dl>
  </section>
  <section class="site change">
    <h3>🌐 change.org<small>世界中の人々の力で、変化を起こす。</small></h3>
    <dl>
      <dt>運営会社</dt><dd>Change.org, Inc.（アメリカの会社）</dd>
      <dt>本社</dt><dd>アメリカ・カリフォルニア州サンフランシスコ</dd>
      <dt>サービス開始</dt><dd>2007年</dd>
      <dt>主に使っている人</dt><dd>世界中の個人・団体（日本からも使えます）</dd>
      <dt>特徴</dt><dd><ul>
        <li>世界最大級の署名サイト</li>
        <li>世界中の署名活動を作ったり、応援したりできる</li>
        <li>英語を中心に、いろいろな言語に対応</li>
      </ul></dd>
    </dl>
  </section>
</div>

<h2 class="section-h">💗 支援金（お金での応援）の違い</h2>
<p>どちらのサイトも、署名のあとに「お金で応援しませんか」という画面が出ることがあります。<b>お金を払わなくても、署名だけで参加できます。</b>ただし、払ったお金の行き先が違います。</p>
<div class="cols">
  <div class="pay voice">
    <h3>Voice の「エール」</h3>
    <ul>
      <li>寄付は「エール」として署名ページに表示されます。</li>
      <li>集まったエールは、<b>署名を始めた人（発起人）</b>に届きます（手数料を引いた額）。</li>
      <li>受け取ったお金は、活動の宣伝・調査・イベントなどに使えます。</li>
      <li>エールは任意で、署名だけの参加もできます。</li>
    </ul>
  </div>
  <div class="pay change">
    <h3>change.org の支援金（寄付）</h3>
    <ul>
      <li>お金は署名を始めた人ではなく、<b>change.org（運営会社）</b>に支払われます。</li>
      <li>集まったお金は、change.org の運営や、ほかのキャンペーンの応援に使われます。</li>
      <li>署名を始めた人が、個別に受け取ることはできません。</li>
      <li>寄付は任意で、署名だけの参加もできます。</li>
    </ul>
  </div>
</div>

<h2 class="section-h">✅ 署名するときのポイント</h2>
<div class="notes-main">
  __PLEASE_IMG__
  <ul class="checklist">
    <li><b>お金を払わなくても署名は有効です。</b>支払い画面が出ても、そのまま閉じてかまいません。</li>
    <li><b>発起人を直接応援したいときは注意。</b>change.org の支援金は、署名を始めた人には届きません。</li>
    <li><b>概要と発起人を確かめてから。</b>どちらのサイトでも、署名する前に内容を確かめて、ご自身で判断してください。</li>
  </ul>
</div>

<p style="margin-top:28px"><a class="btn btn-primary" href="./">← 署名の一覧にもどる</a></p>
</main>
__FOOTER__
<script>
__COMMON_JS__
</script>
</body>
</html>
"""


def build_sites_page(config):
    """署名サイトの違いを説明するページ docs/sites.html を作る。"""
    page = SITES_TEMPLATE
    for key, value in {
        "__HEAD__": page_head(""),
        "__TOPBAR__": topbar("", config["site_name"]),
        "__FOOTER__": footer(""),
        "__CHECK_IMG__": illust_img("", "check", "どちらのサイトかな？と確かめる、しょめたん"),
        "__PLEASE_IMG__": illust_img("", "please", "手をあわせて「確かめてね」とおねがいする、しょめたん"),
        "__COMMON_JS__": COMMON_JS,
        "__SITE_NAME__": html.escape(config["site_name"]),
        "__SITE_URL__": html.escape(config["site_url"]),
    }.items():
        page = page.replace(key, value)
    (OUT_DIR / "sites.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
