"""data.json から公開用のページを作る。

- docs/index.html   … 一覧ページ
- docs/p/番号.html  … 1件ごとのまとめページ（スクショ・署名数の推移グラフつき）

載せるのは「掲載」になっている署名だけ（「候補」「非掲載」「終了」は載せない）。

使い方:  python build.py
"""
import hashlib
import html
import json
from datetime import date
from pathlib import Path

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


def md(iso):
    d = date.fromisoformat(iso)
    return f"{d.month}/{d.day}"


def share_text(it, main_hashtag, hashtag_of, site_url):
    """1件ごとの投稿の定型文（一覧ページの「𝕏でシェア」と投稿文ページで共通）。
    リンク（23字として数える）込みで140字以内にする。"""
    tags = " ".join([main_hashtag] + [hashtag_of[t] for t in it["tags"] if hashtag_of.get(t)])
    head = "⭐【おすすめ署名】" if it.get("pick") else "✍️【署名募集中】"
    n = latest_count(it)
    people = f"いま{n:,}人が賛同しています。\n" if n else ""
    until = f"（{md(it['end'])}まで）" if it.get("end") else ""
    make = lambda title: (f"{head}{until}\n\n「{title}」\n\n{people}"
                          f"あなたも一筆を🙏\n{tags}\n\n")
    title = it["title"]
    while len(make(title)) + 23 > 140 and len(title) > 8:
        title = title[:-2].rstrip("…") + "…"
    return make(title) + site_url + summary_path(it)


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

    rows = []
    for it in items:
        g = growth(it)
        rows.append({
            "id": it["id"], "site": it["site"], "url": it["url"], "title": it["title"],
            "starter": it.get("starter", ""), "target": it.get("target", ""),
            "start": it.get("start", ""), "end": it.get("end", ""),
            "tags": it["tags"], "pref": it.get("pref", ""), "pick": bool(it.get("pick")),
            "found": it.get("found", ""), "count": latest_count(it),
            "grow": g[0] if g else None, "growFrom": g[1] if g else None, "rate": g[2] if g else 0,
            "page": summary_path(it), "share": share_text(it, config["main_hashtag"], hashtag_of, config["site_url"]),
        })
    build_summary_pages(items, tags, config, hashtag_of)

    chara_all = chara_path(config.get("chara_all", ""))
    payload = {
        "updated": data.get("updated", ""),
        "items": rows,
        "tags": [{"name": t["name"], "color": t["color"], "chara": chara_path(t.get("chara", ""))} for t in tags],
        "charaAll": chara_all,
        "charaPick": chara_path(config.get("chara_pick", "")),
        "urgentDays": config["urgent_days"],
    }
    page = TEMPLATE
    for key, value in {
        "__SITE_NAME__": html.escape(config["site_name"]),
        "__SITE_DESC__": html.escape(config["site_description"]),
        "__SITE_URL__": html.escape(config["site_url"]),
        "__COUNT__": str(len(items)),
        "__CHARA_ALL__": html.escape(chara_all),
        "__OG_IMAGE__": f'<meta property="og:image" content="{html.escape(config["site_url"] + chara_all)}">' if chara_all else "",
        "__SIGNED_JS__": SIGNED_JS,
        "__SHARE_JS__": SHARE_JS,
        "__DATA__": json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"),
    }.items():
        page = page.replace(key, value)

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "index.html").write_text(page, encoding="utf-8")
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    print(f"docs/index.html を作りました（掲載 {len(items)} 件）")


def chart_svg(it):
    """署名数の推移を、外部の部品を使わない簡単な線グラフ（SVG）にする。"""
    c = sorted_counts(it)
    if len(c) < 2:
        return '<p class="sub">署名数の記録がたまると、ここに推移のグラフが出ます。</p>'
    W, H, L, R, T, B = 600, 220, 64, 16, 16, 34
    d0 = date.fromisoformat(c[0][0])
    span = max((date.fromisoformat(c[-1][0]) - d0).days, 1)
    lo, hi = min(n for _, n in c), max(n for _, n in c)
    if hi == lo:
        hi = lo + 1
    x = lambda d: L + (date.fromisoformat(d) - d0).days / span * (W - L - R)
    y = lambda n: T + (1 - (n - lo) / (hi - lo)) * (H - T - B)
    pts = " ".join(f"{x(d):.1f},{y(n):.1f}" for d, n in c)
    dots = "".join(f'<circle cx="{x(d):.1f}" cy="{y(n):.1f}" r="3.5"><title>{md(d)}：{n:,}人</title></circle>' for d, n in c)
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

    for it in items:
        n = latest_count(it)
        g = growth(it)
        img = image_of(it)
        img_abs = img if img.startswith("http") else (site_url + img if img else "")
        img_rel = img if img.startswith("http") else ("../" + img if img else "")
        facts = [("発起人", it.get("starter")), ("提出先", it.get("target")),
                 ("開始日", it.get("start")), ("終了日", it.get("end")),
                 ("目標", f"{it['goal']:,}人" if it.get("goal") else ""),
                 ("署名サイト", it["site"] if it["site"] != "Change" else "change.org")]
        facts_html = "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in facts if v)
        grow_html = (f'<span class="grow">前回（{md(g[1])}）から +{g[0]:,}人</span>' if g and g[0] > 0 else "")
        desc = f"いま{n:,}人が賛同。{it.get('summary', '')}" if n else it.get("summary", "")
        replace = {
            "__TITLE__": e(it["title"]),
            "__PICK__": '<span class="pick">⭐おすすめ</span>' if it.get("pick") else "",
            "__TAGS__": "".join(f'<span class="tag" style="background:{color_of.get(t, "#6b7280")}">{e(t)}</span>' for t in it["tags"]),
            "__PREF__": f'<span class="cat">{e(it["pref"])}</span>' if it.get("pref") else "",
            "__IMG__": f'<img class="shot" src="{e(img_rel)}" alt="署名ページの画面" loading="lazy">' if img_rel else "",
            "__COUNT__": f"{n:,}" if n else "—",
            "__GROW__": grow_html,
            "__SUMMARY__": e(it.get("summary", "")),
            "__FACTS__": facts_html,
            "__CHART__": chart_svg(it),
            "__URL__": e(it["url"]),
            "__SITE__": "change.org" if it["site"] == "Change" else "Voice",
            "__END_ISO__": e(it.get("end") or ""),
            "__SHARE__": json.dumps(share_text(it, config["main_hashtag"], hashtag_of, site_url), ensure_ascii=False).replace("</", "<\\/"),
            "__SHARE_JS__": SHARE_JS,
            "__SIGNED_JS__": SIGNED_JS,
            "__ID__": json.dumps(it["id"]),
            "__CHANGE_NOTE__": ("<li>change.org はご自身で判断してください。</li>"
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


BASE_CSS = r"""
:root{--bg:#f6f5f2;--card:#fff;--ink:#1c1b19;--sub:#5f5c56;--line:#e3e0d9;--accent:#1d4ed8;--urgent:#dc2626;--urgent-bg:#fef2f2;--chip:#efede8;--pick:#b45309;--pick-bg:#fff7e0;--up:#15803d}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#16161a;--card:#202026;--ink:#ecebe8;--sub:#a8a59f;--line:#34343c;--accent:#7aa2ff;--urgent:#f87171;--urgent-bg:#3a1e1e;--chip:#2c2c33;--pick:#fbbf24;--pick-bg:#3a3020;--up:#4ade80}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Hiragino Sans","Noto Sans JP","Yu Gothic UI","Meiryo",sans-serif;line-height:1.6}
a{color:var(--accent)}
.tag{color:#fff;padding:1px 8px;border-radius:6px;font-weight:600}
.cat{background:var(--chip);padding:1px 8px;border-radius:6px;color:var(--sub)}
.pick{background:var(--pick-bg);color:var(--pick);padding:1px 8px;border-radius:6px;font-weight:700;border:1px solid var(--pick)}
.left{font-weight:700;padding:1px 8px;border-radius:6px;background:var(--chip);color:var(--ink)}
.left.urgent{background:var(--urgent-bg);color:var(--urgent)}
.grow{color:var(--up);font-weight:600}
.btn{display:inline-block;border:0;cursor:pointer;font-family:inherit;text-decoration:none;border-radius:8px;padding:5px 12px;font-size:.82rem;font-weight:600}
.btn.go{background:var(--accent);color:#fff}
.btn.sum{background:var(--chip);color:var(--ink)}
.btn.x{background:var(--ink);color:var(--bg)}
.btn.done{background:var(--chip);color:var(--sub);border:1.5px dashed var(--line)}
.btn.done.on{background:var(--up);color:#fff;border-style:solid;border-color:transparent}
.signedmark{background:var(--up);color:#fff;padding:1px 8px;border-radius:6px;font-weight:700}
.toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:9px 18px;border-radius:10px;font-size:.92rem;opacity:0;transition:opacity .2s;pointer-events:none;z-index:9}
.toast.show{opacity:1}
.notice{background:var(--pick-bg);border:1.5px solid var(--pick);border-radius:12px;padding:10px 14px;margin:12px 0;font-size:.88rem;line-height:1.6}
.notice b.h{display:block;color:var(--pick);margin-bottom:2px}
.notice ul{margin:0;padding-left:1.2em}
.notice li{margin:2px 0}
"""


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
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>✍️</text></svg>">
<style>
""" + BASE_CSS + r"""
body{line-height:1.7}
.wrap{max-width:640px;margin:0 auto;padding:12px 16px 40px}
.back{font-size:.88rem;text-decoration:none}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 6px;font-size:.8rem}
h1{font-size:1.3rem;line-height:1.5;margin:4px 0 12px}
.shot{width:100%;border:1px solid var(--line);border-radius:12px;display:block;margin:0 0 12px}
.countbox{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.countbox b{font-size:1.6rem}
.countbox small{color:var(--sub)}
.btns{display:flex;flex-direction:column;gap:8px;margin:14px 0}
.btns .btn{display:block;text-align:center;border-radius:12px;padding:14px;font-size:1.05rem;font-weight:700;width:100%}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:12px 0}
h2{font-size:1rem;margin:0 0 6px}
dl{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:0}
dt{color:var(--sub);font-size:.88rem}
dd{margin:0;word-break:break-word}
.chart{width:100%;height:auto;display:block}
.chart polyline{fill:none;stroke:var(--accent);stroke-width:2.5}
.chart circle{fill:var(--accent)}
.chart text{fill:var(--sub);font-size:12px}
.chart .axis{stroke:var(--line)}
.sub{color:var(--sub);font-size:.85rem}
footer{font-size:.78rem;color:var(--sub);margin-top:20px}
</style>
</head>
<body>
<div class="wrap">
<a class="back" href="../">← 署名の一覧（__SITE_NAME__）</a>
<div class="meta">__PICK____TAGS____PREF__<span class="left" id="left" hidden></span></div>
<h1>__TITLE__</h1>
__IMG__
<div class="countbox"><span><small>賛同者</small> <b>__COUNT__</b> 人</span>__GROW__</div>

<div class="notice" role="note">
  <b class="h">⚠️ 署名する前にご確認ください</b>
  <ul>
    <li>下の「どんな署名？」と「発起人」を必ず確認してから署名してください。</li>
    __CHANGE_NOTE__
  </ul>
</div>

<div class="btns">
  <a class="btn go" href="__URL__" target="_blank" rel="noopener">__SITE__ で署名する</a>
  <button type="button" class="btn x" id="share">𝕏でシェアして広める</button>
  <button type="button" class="btn done" id="signed">☐ 署名した（この端末に記録）</button>
</div>

<section>
  <h2>📝 どんな署名？</h2>
  <p>__SUMMARY__</p>
  <p class="sub">※ 署名ページの本文の書き出しです。全文は署名ページでご確認ください。</p>
</section>

<section>
  <h2>📋 基本情報</h2>
  <dl>__FACTS__</dl>
</section>

<section>
  <h2>📈 署名数の推移</h2>
  __CHART__
</section>

<footer>このページは署名サイトの公開情報をまとめたものです。署名数は当サイトが確認した日の人数です。正確な内容は必ず署名ページでご確認ください。</footer>
</div>
<script>
__SHARE_JS__
const end = '__END_ISO__';
if (end) {
  const ymd = d => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  const dl = Math.round((Date.UTC(...end.split('-').map((v, i) => i === 1 ? v - 1 : +v)) - ymd(new Date())) / 86400000);
  const left = document.getElementById('left');
  left.hidden = false;
  left.textContent = dl < 0 ? '終了' : dl === 0 ? '本日終了' : `あと${dl}日`;
  if (dl <= __URGENT_DAYS__) left.classList.add('urgent');
}
document.getElementById('share').onclick = () => shareX(__SHARE__);
__SIGNED_JS__
const ID = __ID__;
const sb = document.getElementById('signed');
const paint = () => {
  const on = !!loadSigned()[ID];
  sb.classList.toggle('on', on);
  sb.setAttribute('aria-pressed', on);
  sb.textContent = on ? '✅ 署名済み（もう一度押すと取り消し）' : '☐ 署名した（この端末に記録）';
};
sb.onclick = () => { toggleSigned(ID); paint(); };
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
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>✍️</text></svg>">
<style>
""" + BASE_CSS + r"""
.wrap{max-width:860px;margin:0 auto;padding:0 16px}
header{padding:28px 0 12px}
h1{font-size:1.6rem;margin:0 0 4px;letter-spacing:.02em}
.lead{color:var(--sub);margin:0 0 12px;font-size:.95rem}
.stats{display:flex;gap:10px;flex-wrap:wrap;font-size:.85rem;color:var(--sub)}
.stats b{color:var(--ink);font-size:1.1rem}
.filters{position:sticky;top:0;z-index:5;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line)}
.tagbar{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.tagbtn{border:1.5px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:5px 12px;font-size:.88rem;cursor:pointer;font-family:inherit}
.tagbtn .n{opacity:.7;margin-left:4px;font-size:.8em}
.tagbtn[aria-pressed="true"]{color:#fff;border-color:transparent}
.row{display:flex;gap:6px;flex-wrap:wrap}
.row input{flex:1 1 220px}
.row select{flex:1 1 110px}
.row input,.row select{min-width:0;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);font-size:.92rem;font-family:inherit}
.count{font-size:.85rem;color:var(--sub);margin:10px 0 4px}
ul.list{list-style:none;padding:0;margin:0 0 40px}
.item{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:10px 0;border-left:5px solid var(--tagc,var(--line))}
.item.picked{background:linear-gradient(var(--pick-bg),var(--card) 60px)}
.meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:.8rem;color:var(--sub);margin-bottom:4px}
.item h2{font-size:1rem;margin:4px 0 6px;font-weight:600;line-height:1.5}
.item h2 a{color:var(--ink);text-decoration:none}
.item h2 a:hover{text-decoration:underline}
.who{font-size:.8rem;color:var(--sub);margin:0 0 8px;line-height:1.5;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.num{font-size:.9rem;margin:0 0 8px}
.num b{font-size:1.15rem}
.foot{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;font-size:.82rem;color:var(--sub)}
.actions{display:flex;gap:6px;flex-wrap:wrap}
.empty{text-align:center;color:var(--sub);padding:40px 0}
.chara{margin:4px auto 12px;max-width:560px}
.chara img{width:100%;height:auto;display:block;border-radius:14px;border:1px solid var(--line);transition:opacity .2s}
.chara img.fade{opacity:0}
.item.signed{opacity:.75}
.hide-signed{display:inline-flex;align-items:center;gap:4px;font-size:.88rem;color:var(--sub);cursor:pointer;white-space:nowrap}
footer{font-size:.8rem;color:var(--sub);padding:20px 0 40px;border-top:1px solid var(--line)}
</style>
</head>
<body>
<div class="wrap">
<header>
  <p style="font-size:.85rem;margin:0 0 10px"><a href="posts.html">📣 X投稿文ページ</a></p>
  <h1>✍️ __SITE_NAME__</h1>
  <p class="lead">__SITE_DESC__</p>
  <div class="stats"><span>掲載中 <b>__COUNT__</b> 件</span><span id="mine"></span><span id="updated"></span></div>
  <div class="notice" role="note">
    <b class="h">⚠️ 署名する前にご確認ください</b>
    <ul>
      <li>このページでは、change.org と Voice の2つの署名サイトをキーワードで検索し、その中から運営者が選んだ署名を載せています。内容を保証するものではありません。</li>
      <li>署名する前に、必ず<b>概要</b>と<b>発起人</b>を確認してください。</li>
      <li>change.org の署名については、内容をよく確かめたうえで、ご自身で判断してください。</li>
    </ul>
  </div>
</header>

<figure class="chara"><img id="chara" src="__CHARA_ALL__" alt="しょめたん（署名をあつめる妖精）" width="800" height="533"></figure>

<div class="filters">
  <div class="tagbar" id="tagbar" role="group" aria-label="テーマで絞り込み"></div>
  <div class="row">
    <input id="q" type="search" placeholder="キーワードで探す（例：大阪、墓地）">
    <select id="pref"><option value="">すべての地域</option></select>
    <select id="sort">
      <option value="count">署名が多い順</option>
      <option value="rate">最近伸びている順</option>
      <option value="end">終了日が近い順</option>
      <option value="new">新着順</option>
    </select>
    <label class="hide-signed"><input type="checkbox" id="hideSigned"> 署名済みを隠す</label>
  </div>
</div>

<p class="count" id="count"></p>
<ul class="list" id="list"></ul>

<footer>
  出典：<a href="https://www.change.org/" target="_blank" rel="noopener">change.org</a>・<a href="https://voice.charity/" target="_blank" rel="noopener">Voice</a> の公開情報。
  署名数は当サイトが確認した日の人数で、最新の人数とは異なる場合があります。必ず署名ページで内容をご確認ください。
</footer>
</div>

<div class="toast" id="toast" role="status"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
__SIGNED_JS__
const D = JSON.parse(document.getElementById('data').textContent);
const tagColor = Object.fromEntries(D.tags.map(t => [t.name, t.color]));
const charaOf = Object.fromEntries(D.tags.map(t => [t.name, t.chara]));
const state = { tag: '', q: '', pref: '', sort: 'count', hideSigned: false };
const PICK = '__pick__';

// タブに合わせて、しょめたんの絵を切り替える（そのテーマの絵が無ければ「すべて」の絵）
function showChara(){
  const img = document.getElementById('chara');
  const src = (state.tag === PICK ? D.charaPick : charaOf[state.tag]) || D.charaAll;
  if (!src || img.getAttribute('src') === src) return;
  img.classList.add('fade');
  setTimeout(() => { img.onload = () => img.classList.remove('fade'); img.src = src; }, 150);
}
function toast(msg){
  const t = document.getElementById('toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 1800);
}

function ymd(d){ return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()); }
function daysLeft(iso){ const [y,m,d] = iso.split('-').map(Number); return Math.round((Date.UTC(y, m-1, d) - ymd(new Date())) / 86400000); }
function md(iso){ const [, m, d] = iso.split('-').map(Number); return `${m}/${d}`; }
function esc(s){ return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
const num = n => n == null ? '—' : n.toLocaleString();

[...new Set(D.items.map(i => i.pref).filter(Boolean))].sort().forEach(p => {
  const o = document.createElement('option'); o.value = o.textContent = p;
  document.getElementById('pref').appendChild(o);
});

const tagbar = document.getElementById('tagbar');
const buttons = [{name:'', label:'すべて', color:'#444', n:D.items.length},
                 {name:PICK, label:'⭐おすすめ', color:'#b45309', n:D.items.filter(i => i.pick).length},
                 ...D.tags.map(t => ({...t, label:t.name, n:D.items.filter(i => i.tags.includes(t.name)).length}))];
buttons.filter(t => t.name === '' || t.n).forEach(t => {
  const b = document.createElement('button');
  b.className = 'tagbtn'; b.type = 'button';
  b.innerHTML = `${esc(t.label)}<span class="n">${t.n}</span>`;
  b.dataset.tag = t.name; b.dataset.color = t.color;
  b.onclick = () => { state.tag = t.name; showChara(); render(); };
  tagbar.appendChild(b);
});
document.getElementById('hideSigned').onchange = e => { state.hideSigned = e.target.checked; render(); };

document.getElementById('q').oninput = e => { state.q = e.target.value.trim(); render(); };
document.getElementById('pref').onchange = e => { state.pref = e.target.value; render(); };
document.getElementById('sort').onchange = e => { state.sort = e.target.value; render(); };
if (D.updated) document.getElementById('updated').textContent = '署名数の確認日：' + D.updated;

const sorters = {
  count: (a, b) => (b.count || 0) - (a.count || 0),
  rate:  (a, b) => (b.rate || 0) - (a.rate || 0),
  end:   (a, b) => (a.end || '9999') < (b.end || '9999') ? -1 : (a.end || '9999') > (b.end || '9999') ? 1 : 0,
  new:   (a, b) => (b.found + b.start) < (a.found + a.start) ? -1 : 1,
};

function render(){
  const signed = loadSigned();
  const mineN = D.items.filter(i => signed[i.id]).length;
  document.getElementById('mine').innerHTML = mineN ? `あなたの署名 <b>${mineN}</b> 件` : '';
  tagbar.querySelectorAll('.tagbtn').forEach(b => {
    const on = b.dataset.tag === state.tag;
    b.setAttribute('aria-pressed', on);
    b.style.background = on ? b.dataset.color : '';
  });
  const items = D.items.filter(i =>
    (!state.tag || (state.tag === PICK ? i.pick : i.tags.includes(state.tag))) &&
    (!state.pref || i.pref === state.pref) &&
    (!state.hideSigned || !signed[i.id]) &&
    (!state.q || (i.title + i.starter + i.target + i.pref).includes(state.q))
  ).sort((a, b) => (b.pick - a.pick) || sorters[state.sort](a, b));   // おすすめはいつも先頭
  const label = document.querySelector('#sort option:checked').textContent;
  document.getElementById('count').textContent = `${items.length} 件を表示中（⭐おすすめ → ${label}）`;
  const list = document.getElementById('list');
  if (!items.length){ list.innerHTML = '<li class="empty">条件に合う署名はありません</li>'; return; }
  list.innerHTML = items.map(i => {
    const first = i.tags[0];
    let left = '';
    if (i.end) {
      const dl = daysLeft(i.end);
      left = `<span class="left${dl <= D.urgentDays ? ' urgent' : ''}">${dl <= 0 ? '本日終了' : `あと${dl}日`}</span>`;
    }
    const who = [i.starter && `発起人：${esc(i.starter)}`, i.target && `提出先：${esc(i.target)}`].filter(Boolean).join('　');
    const done = !!signed[i.id];
    return `<li class="item${i.pick ? ' picked' : ''}${done ? ' signed' : ''}" style="${first ? '--tagc:' + tagColor[first] : ''}">
      <div class="meta">${done ? '<span class="signedmark">✅署名済み</span>' : ''}${i.pick ? '<span class="pick">⭐おすすめ</span>' : ''}${left}
        ${i.tags.map(t => `<span class="tag" style="background:${tagColor[t]}">${esc(t)}</span>`).join('')}
        ${i.pref ? `<span class="cat">${esc(i.pref)}</span>` : ''}<span class="cat">${i.site === 'Change' ? 'change.org' : 'Voice'}</span></div>
      <h2><a href="${esc(i.page)}">${esc(i.title)}</a></h2>
      ${who ? `<p class="who">${who}</p>` : ''}
      <p class="num">賛同 <b>${num(i.count)}</b> 人 ${i.grow > 0 ? `<span class="grow">（${md(i.growFrom)}から +${num(i.grow)}）</span>` : ''}</p>
      <div class="foot"><span>${i.end ? `終了日 ${md(i.end)}` : ''}</span>
        <span class="actions"><a class="btn sum" href="${esc(i.page)}">まとめ</a>
        <a class="btn go" href="${esc(i.url)}" target="_blank" rel="noopener">署名ページへ</a>
        <button type="button" class="btn x" data-id="${esc(i.id)}">𝕏でシェア</button>
        <button type="button" class="btn done${done ? ' on' : ''}" data-signed="${esc(i.id)}" aria-pressed="${done}">${done ? '✅署名した' : '☐署名した'}</button></span></div>
    </li>`;
  }).join('');
}
render();
__SHARE_JS__
document.getElementById('list').addEventListener('click', e => {
  const s = e.target.closest('button[data-signed]');
  if (s) { toast(toggleSigned(s.dataset.signed) ? '✅ 署名済みにしました。ありがとう！' : '署名済みを取り消しました'); render(); return; }
  const b = e.target.closest('button.x'); if (!b) return;
  shareX(D.items.find(x => x.id === b.dataset.id).share);
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
