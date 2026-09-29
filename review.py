"""候補の署名を選ぶための画面（自分のパソコンの中だけで動く）。

使い方:  python review.py
  → ブラウザが開きます。「載せる」「載せない」「⭐おすすめ」を押すと、その場で data.json に保存されます。
  → 終わったら、この黒い画面で Ctrl + C を押して閉じてください。
"""
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from collect import DATA_PATH, PREFS, load_json, save_json

HERE = Path(__file__).parent
PORT = 8765
STATUSES = ("候補", "掲載", "非掲載", "終了")
lock = threading.Lock()


def tag_names():
    config = load_json(HERE / "config.json", {"tags": []})
    names = [t["name"] for t in config["tags"]]
    for theme in load_json(HERE / "keywords.json", {}).values():
        if theme["tag"] not in names:
            names.append(theme["tag"])
    return names


def apply_update(body):
    """画面から届いた変更を data.json に書き込む。"""
    with lock:
        data = load_json(DATA_PATH, {"items": {}})
        changed = []
        for item_id in body.get("ids", []):
            it = data["items"].get(item_id)
            if not it:
                continue
            if body.get("status") in STATUSES:
                it["status"] = body["status"]
                if it["status"] == "非掲載":
                    it["pick"] = False
                    # 載せない署名のスクショは消して容量を節約する
                    if it.get("image"):
                        (HERE / "docs" / it["image"]).unlink(missing_ok=True)
                        it["image"] = ""
            if "pick" in body:
                it["pick"] = bool(body["pick"])
                if it["pick"] and it["status"] == "候補":
                    it["status"] = "掲載"  # おすすめにしたものは載せる
            if isinstance(body.get("tags"), list):
                it["tags"] = [t for t in body["tags"] if isinstance(t, str) and t]
            if isinstance(body.get("pref"), str):
                it["pref"] = body["pref"]
            changed.append(it)
        save_json(DATA_PATH, data)
        return changed


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 画面に通信の記録を出さない

    def send(self, code, body, ctype):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/":
            self.send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/data":
            data = load_json(DATA_PATH, {"items": {}})
            payload = {"items": list(data["items"].values()), "tags": tag_names(), "prefs": PREFS}
            self.send(200, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/img/"):
            f = (HERE / "docs" / self.path.lstrip("/")).resolve()
            if f.is_file() and (HERE / "docs" / "img").resolve() in f.parents:
                self.send(200, f.read_bytes(), "image/jpeg")
            else:
                self.send(404, "not found", "text/plain")
        else:
            self.send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/update":
            self.send(404, "not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        changed = apply_update(body)
        self.send(200, json.dumps(changed, ensure_ascii=False), "application/json; charset=utf-8")


PAGE = r"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>署名の選別（自分用）</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1c1b19;--sub:#5f5c56;--line:#e3e0d9;--accent:#1d4ed8;--ok:#15803d;--ng:#b91c1c;--pick:#b45309;--pick-bg:#fff7e0;--chip:#efede8}
@media (prefers-color-scheme: dark){:root{--bg:#16161a;--card:#202026;--ink:#ecebe8;--sub:#a8a59f;--line:#34343c;--accent:#7aa2ff;--ok:#4ade80;--ng:#f87171;--pick:#fbbf24;--pick-bg:#3a3020;--chip:#2c2c33}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Hiragino Sans","Noto Sans JP","Yu Gothic UI","Meiryo",sans-serif;line-height:1.6}
.wrap{max-width:980px;margin:0 auto;padding:0 16px 60px}
h1{font-size:1.3rem;margin:20px 0 4px}
.help{color:var(--sub);font-size:.88rem;margin:0 0 10px}
.bar{position:sticky;top:0;z-index:5;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);display:flex;flex-direction:column;gap:8px}
.tabs,.row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.tab{border:1.5px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:5px 14px;cursor:pointer;font-family:inherit;font-size:.9rem}
.tab[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:transparent}
.row input,.row select{padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);font-family:inherit;font-size:.9rem;min-width:0;flex:1 1 150px}
.bulk{margin-left:auto;border:1px solid var(--ng);color:var(--ng);background:transparent;border-radius:8px;padding:6px 12px;cursor:pointer;font-family:inherit}
.card{display:grid;grid-template-columns:180px 1fr;gap:14px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin:10px 0}
.card.picked{border-color:var(--pick);background:linear-gradient(var(--pick-bg),var(--card) 80px)}
.card img{width:180px;height:120px;object-fit:cover;border-radius:8px;background:var(--chip)}
.noimg{width:180px;height:120px;border-radius:8px;background:var(--chip);display:grid;place-items:center;color:var(--sub);font-size:.8rem}
@media (max-width:600px){.card{grid-template-columns:1fr}.card img,.noimg{width:100%;height:160px}}
.card h2{font-size:1rem;margin:0 0 4px;line-height:1.5}
.card h2 a{color:var(--ink)}
.meta{font-size:.8rem;color:var(--sub);display:flex;gap:10px;flex-wrap:wrap}
.meta b{color:var(--ink)}
.sum{font-size:.85rem;margin:6px 0;color:var(--sub)}
.edit{display:flex;gap:10px;flex-wrap:wrap;align-items:center;font-size:.82rem;margin:6px 0}
.edit label{display:inline-flex;gap:3px;align-items:center;cursor:pointer}
.edit select{padding:3px 6px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink);font-family:inherit}
.acts{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.acts button{border:0;border-radius:8px;padding:7px 14px;font-weight:700;cursor:pointer;font-family:inherit;font-size:.88rem}
.b-ok{background:var(--ok);color:#fff}.b-ng{background:var(--chip);color:var(--ng)}
.b-pick{background:var(--chip);color:var(--pick)}.b-pick.on{background:var(--pick);color:#fff}
.b-back{background:var(--chip);color:var(--ink)}
.st{font-size:.78rem;font-weight:700;padding:1px 8px;border-radius:6px;background:var(--chip)}
.more{display:block;margin:16px auto;padding:10px 24px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer;font-family:inherit}
.toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:8px 16px;border-radius:8px;font-size:.9rem;opacity:0;transition:opacity .2s}
.toast.show{opacity:1}
</style></head>
<body><div class="wrap">
<h1>✍️ 署名の選別（自分用の画面）</h1>
<p class="help">「載せる」を押した署名だけが公開ページに出ます。押すとすぐ保存されます。終わったら黒い画面で Ctrl + C を押して閉じてください。</p>
<div class="bar">
  <div class="tabs" id="tabs"></div>
  <div class="row">
    <input id="q" type="search" placeholder="タイトル・発起人・提出先で探す">
    <select id="kw"><option value="">すべてのキーワード</option></select>
    <select id="sort"><option value="count">署名が多い順</option><option value="start">開始が新しい順</option><option value="found">見つけた日が新しい順</option></select>
    <button class="bulk" id="bulk" type="button">表示中の候補をすべて「載せない」</button>
  </div>
</div>
<p class="help" id="count"></p>
<div id="list"></div>
<button class="more" id="more" type="button" hidden>もっと見る</button>
</div>
<div class="toast" id="toast"></div>
<script>
let D = {items: [], tags: [], prefs: []};
const state = {status: '候補', q: '', kw: '', sort: 'count', shown: 40};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const latest = it => { const k = Object.keys(it.counts).sort(); return k.length ? it.counts[k[k.length - 1]] : 0; };

function toast(msg){ const t = document.getElementById('toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 1500); }

async function update(ids, change, msg){
  const r = await fetch('/api/update', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ids, ...change})});
  if (!r.ok) { alert('保存できませんでした。黒い画面にエラーが出ていないか確認してください。'); return; }
  for (const it of await r.json()) { const i = D.items.findIndex(x => x.id === it.id); D.items[i] = it; }
  if (msg) toast(msg);
  render();
}

function filtered(){
  return D.items.filter(i => i.status === state.status &&
      (!state.kw || i.keywords.includes(state.kw)) &&
      (!state.q || (i.title + i.starter + i.target + i.summary).includes(state.q)))
    .sort((a, b) => state.sort === 'count' ? latest(b) - latest(a) : (b[state.sort] || '').localeCompare(a[state.sort] || ''));
}

function card(i){
  const img = i.image ? '/' + i.image : i.photo;
  const tags = D.tags.map(t => `<label><input type="checkbox" data-tag="${esc(t)}" ${i.tags.includes(t) ? 'checked' : ''}>${esc(t)}</label>`).join('');
  const prefs = ['', ...D.prefs].map(p => `<option ${p === i.pref ? 'selected' : ''} value="${esc(p)}">${p || '地域なし'}</option>`).join('');
  const acts = i.status === '候補'
    ? `<button class="b-ok" data-act="掲載">載せる</button><button class="b-ng" data-act="非掲載">載せない</button>`
    : `<button class="b-back" data-act="候補">候補にもどす</button>` + (i.status === '掲載' ? `<button class="b-ng" data-act="非掲載">載せない</button>` : '');
  return `<div class="card${i.pick ? ' picked' : ''}" data-id="${esc(i.id)}">
    ${img ? `<img src="${esc(img)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : '<div class="noimg">画像なし</div>'}
    <div>
      <h2><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a></h2>
      <div class="meta"><span class="st">${esc(i.status)}</span><span>${i.site === 'Change' ? 'change.org' : 'Voice'}</span>
        <span>賛同 <b>${latest(i).toLocaleString()}</b> 人</span>
        ${i.start ? `<span>開始 ${esc(i.start)}</span>` : ''}${i.end ? `<span>終了 ${esc(i.end)}</span>` : ''}
        <span>キーワード：${esc(i.keywords.join('、'))}</span></div>
      <div class="meta">${i.starter ? `<span>発起人：${esc(i.starter)}</span>` : ''}${i.target ? `<span>提出先：${esc(i.target)}</span>` : ''}</div>
      <p class="sum">${esc(i.summary)}</p>
      <div class="edit">タグ：${tags}　地域：<select data-pref>${prefs}</select></div>
      <div class="acts">${acts}<button class="b-pick${i.pick ? ' on' : ''}" data-pick>${i.pick ? '⭐おすすめ中' : '☆おすすめにする'}</button></div>
    </div></div>`;
}

function render(){
  const tabs = document.getElementById('tabs');
  tabs.innerHTML = ['候補','掲載','非掲載','終了'].map(s =>
    `<button class="tab" type="button" data-s="${s}" aria-pressed="${s === state.status}">${s} ${D.items.filter(i => i.status === s).length}</button>`).join('');
  const items = filtered();
  document.getElementById('count').textContent = `${items.length} 件`;
  document.getElementById('list').innerHTML = items.slice(0, state.shown).map(card).join('') || '<p class="help">ありません</p>';
  document.getElementById('more').hidden = items.length <= state.shown;
  document.getElementById('bulk').hidden = state.status !== '候補' || !items.length;
}

document.getElementById('tabs').onclick = e => { const b = e.target.closest('[data-s]'); if (b) { state.status = b.dataset.s; state.shown = 40; render(); } };
document.getElementById('q').oninput = e => { state.q = e.target.value.trim(); state.shown = 40; render(); };
document.getElementById('kw').onchange = e => { state.kw = e.target.value; state.shown = 40; render(); };
document.getElementById('sort').onchange = e => { state.sort = e.target.value; render(); };
document.getElementById('more').onclick = () => { state.shown += 40; render(); };
document.getElementById('bulk').onclick = () => {
  const ids = filtered().map(i => i.id);
  if (confirm(`表示中の候補 ${ids.length} 件をすべて「載せない」にします。よろしいですか？`)) update(ids, {status: '非掲載'}, `${ids.length} 件を「載せない」にしました`);
};
document.getElementById('list').addEventListener('click', e => {
  const c = e.target.closest('.card'); if (!c) return;
  const id = c.dataset.id, it = D.items.find(x => x.id === id);
  const act = e.target.closest('[data-act]');
  if (act) update([id], {status: act.dataset.act}, `「${act.textContent}」にしました`);
  if (e.target.closest('[data-pick]')) update([id], {pick: !it.pick}, it.pick ? 'おすすめを外しました' : '⭐おすすめにしました（掲載にもなります）');
});
document.getElementById('list').addEventListener('change', e => {
  const c = e.target.closest('.card'); if (!c) return;
  if (e.target.matches('[data-tag]')) update([c.dataset.id], {tags: [...c.querySelectorAll('[data-tag]:checked')].map(x => x.dataset.tag)}, 'タグを保存しました');
  if (e.target.matches('[data-pref]')) update([c.dataset.id], {pref: e.target.value}, '地域を保存しました');
});

fetch('/api/data').then(r => r.json()).then(d => {
  D = d;
  [...new Set(D.items.flatMap(i => i.keywords))].sort().forEach(k => {
    const o = document.createElement('option'); o.value = o.textContent = k; document.getElementById('kw').appendChild(o);
  });
  render();
});
</script></body></html>
"""


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"選別の画面を開きます： {url}")
    print("終わったら、この画面で Ctrl + C を押して閉じてください。")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n閉じました。次は `python publish.py` でページを作って公開できます。")


if __name__ == "__main__":
    main()
