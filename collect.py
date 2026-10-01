"""
署名運動の収集ツール

change.org と Voice(voice.charity) を keywords.json のキーワードで検索し、
見つかった署名運動を data.json に「候補」として保存する。
すでに持っている署名運動は、今日の署名数を1つ追記する（署名数の推移がわかる）。
終了した署名運動は「終了」にして、それ以降は追いかけない。

使い方:
    python collect.py --full   … 最初の1回。検索結果を最後のページまで全部見る
    python collect.py          … 2回目から。前回以降の新着だけ見る
"""

import argparse
import ast
import json
import re
import sys
import time
import urllib.parse
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).parent
DATA_PATH = HERE / "data.json"
STATE_PATH = HERE / "state.json"
KEYWORDS_PATH = HERE / "keywords.json"
CONFIG_PATH = HERE / "config.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
REQ_HEADERS = {"User-Agent": UA}

# 追いかける（署名数を記録する）状態。「非掲載」「終了」は追いかけない
TRACKED = ("候補", "掲載")

PREFS = [
    "北海道", "青森", "岩手", "宮城", "秋田", "山形", "福島", "茨城", "栃木", "群馬",
    "埼玉", "千葉", "東京", "神奈川", "新潟", "富山", "石川", "福井", "山梨", "長野",
    "岐阜", "静岡", "愛知", "三重", "滋賀", "京都", "大阪", "兵庫", "奈良", "和歌山",
    "鳥取", "島根", "岡山", "広島", "山口", "徳島", "香川", "愛媛", "高知", "福岡",
    "佐賀", "長崎", "熊本", "大分", "宮崎", "鹿児島", "沖縄",
]

# Voiceはアクセス頻度が高いと429(Too Many Requests)を返すため、
# リクエスト間隔を空け、429時は少し待って自動的に再試行する。
_last_voice_request_time = [0.0]
VOICE_MIN_INTERVAL_SEC = 1.0


def voice_get(url, params=None, max_retries=3):
    for attempt in range(max_retries):
        elapsed = time.time() - _last_voice_request_time[0]
        if elapsed < VOICE_MIN_INTERVAL_SEC:
            time.sleep(VOICE_MIN_INTERVAL_SEC - elapsed)
        r = requests.get(url, params=params, headers=REQ_HEADERS, timeout=20)
        _last_voice_request_time[0] = time.time()
        if r.status_code == 429 and attempt < max_retries - 1:
            wait = 5 * (attempt + 1)
            print(f"  Voiceからレート制限を受けました。{wait}秒待って再試行します...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


# ---------------------------------------------------------------------------
# 保存ファイルの読み書き
# ---------------------------------------------------------------------------

def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    # 書き込み途中で止まってもファイルが壊れないように、別名で書いてから置き換える。
    # Dropboxが同期中でファイルをつかんでいると断られることがあるので、少し待って再挑戦する。
    for attempt in range(10):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(1)


# ---------------------------------------------------------------------------
# 共通の小道具
# ---------------------------------------------------------------------------

def clean_text(s, limit=None):
    """HTMLタグや余計な空白を取り除き、必要なら指定の字数で切る。"""
    s = BeautifulSoup(s or "", "html.parser").get_text(" ")
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[: limit - 1] + "…"
    return s


def guess_pref(*texts):
    """タイトルや提出先に都道府県名が出てくれば、それを地域とする（最初に出たもの）。"""
    joined = " ".join(t for t in texts if t)
    hits = [(joined.find(p), p) for p in PREFS if p in joined]
    return min(hits)[1] if hits else ""



def change_org_petition_url(slug):
    return "https://www.change.org/p/" + urllib.parse.quote(slug, safe="")


# ---------------------------------------------------------------------------
# change.org
# ---------------------------------------------------------------------------

def get_change_org_api_key():
    """change.orgの検索画面を一度開き、検索に使う合言葉（APIキー）を読み取る。"""
    from playwright.sync_api import sync_playwright

    captured = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA)

        def handle_request(request):
            if "/ts/collections" in request.url:
                key = request.headers.get("x-typesense-api-key")
                if key:
                    captured["key"] = key

        page.on("request", handle_request)
        page.goto(
            "https://www.change.org/search?q=%E3%83%86%E3%82%B9%E3%83%88",
            wait_until="networkidle",
            timeout=30000,
        )
        page.wait_for_timeout(2000)
        browser.close()
    return captured.get("key")


def change_starter_name(doc):
    raw = doc.get("starter")
    if isinstance(raw, str):
        try:
            raw = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return ""
    if not isinstance(raw, dict):
        return ""
    if raw.get("display_name"):
        return raw["display_name"]
    return f"{raw.get('last_name') or ''} {raw.get('first_name') or ''}".strip()


def change_doc_to_item(doc):
    """change.orgの検索結果1件を、data.json に保存する形に変える。"""
    created = int(float(doc.get("created_at") or 0))
    photo = doc.get("photo_url") or ""
    ended = (
        str(doc.get("victory")) == "True"
        or str(doc.get("status", "published")).lower() != "published"
        or str(doc.get("hidden")) == "True"
    )
    title = clean_text(doc.get("ask"))
    target = clean_text(doc.get("targeting_description"))
    return {
        "id": f"change:{doc.get('petition_id') or doc.get('id')}",
        "site": "Change",
        "url": change_org_petition_url(doc.get("slug", "")),
        "title": title,
        "summary": clean_text(doc.get("description"), 150),
        "starter": change_starter_name(doc),
        "target": target,
        "start": date.fromtimestamp(created).isoformat() if created else "",
        "end": "",
        "goal": None,
        "photo": f"https://assets.change.org/{photo}" if photo and not photo.startswith("http") else photo,
        "count": int(float(doc.get("total_signature_count") or 0)),
        "created_ts": created,
        "ended": ended,
    }


def search_change_org(keyword, api_key, full, since_ts, title_only=False):
    """change.orgを新しい順に検索する。full=Falseなら since_ts より古くなったところで打ち切る。

    change.orgの検索(Typesense)はデフォルト設定だと、十分な完全一致が無い場合に
    キーワードを無視して無関係な結果まで返すため、num_typos=0 / drop_tokens_threshold=0
    で厳密一致寄りにしたうえで、タイトル・本文に実際にキーワードが含まれるものだけに絞る。
    """
    url = "https://www.change.org/ts/collections/petitions_ja/documents/search"
    headers = dict(REQ_HEADERS)
    headers["X-TYPESENSE-API-KEY"] = api_key
    results = []
    page = 1
    while True:
        params = {
            "q": keyword,
            "query_by": "ask,description",
            "num_typos": 0,
            "drop_tokens_threshold": 0,
            "sort_by": "created_at:desc",
            "page": page,
            "per_page": 100,
        }
        r = requests.get(url, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        hits = r.json().get("hits", [])
        if not hits:
            break
        oldest = None
        for hit in hits:
            item = change_doc_to_item(hit["document"])
            oldest = item["created_ts"] if oldest is None else min(oldest, item["created_ts"])
            desc = hit["document"].get("description") or ""
            if keyword not in item["title"] and (title_only or keyword not in desc):
                continue
            results.append(item)
        print(f"    change.org {page}ページ目（{len(hits)}件中 該当{len(results)}件まで）")
        if not full and oldest is not None and oldest < since_ts:
            break
        page += 1
        time.sleep(0.5)
    return results


def fetch_change_org_detail(url):
    """change.orgの署名ページから最新の署名数と、終了（成功・非公開）かどうかを読む。"""
    r = requests.get(url, headers=REQ_HEADERS, timeout=20)
    r.raise_for_status()
    t = r.text
    m = re.search(r'"signatureCount":\{"displayed":\d+,"total":(\d+)(?:,"goal":(\d+))?', t) or \
        re.search(r'"signatureCount":\{"total":(\d+)', t)
    count = int(m.group(1)) if m else None
    goal = int(m.group(2)) if m and m.lastindex and m.lastindex >= 2 and m.group(2) else None
    s = re.search(r'"status":"([A-Z_]+)","victoryDate":(null|"[^"]*")', t)
    ended = bool(s) and (s.group(1) != "PUBLISHED" or s.group(2) != "null")
    return {"count": count, "goal": goal, "ended": ended}


def fetch_change_org_petition(url):
    """change.orgの署名ページ1件から、data.json に保存するのに必要な情報をまとめて読む（手で追加する用）。"""
    r = requests.get(url, headers=REQ_HEADERS, timeout=20)  # chng.it の短いURLも転送先までたどる
    r.raise_for_status()
    t = r.text
    key = '"pageData":{"petition":'
    i = t.find(key)
    if i < 0:
        raise ValueError("change.orgの署名ページではないようです")
    p, _ = json.JSONDecoder().raw_decode(t, i + len(key))
    sig = (p.get("signatureState") or {})
    count = (sig.get("signatureCount") or {}).get("total")
    goal = (sig.get("signatureGoal") or {}).get("displayed")
    photo = ((p.get("photo") or {}).get("petitionLarge") or {}).get("url") or ""
    if photo.startswith("//"):
        photo = "https:" + photo
    user = p.get("user") or {}
    org = p.get("organization") or {}
    dms = (p.get("dmsWithLegislativeBodiesConnection") or {}).get("nodes") or []
    target = "、".join(n.get("displayName") or n.get("name") or "" for n in dms if isinstance(n, dict)).strip("、")
    return {
        "id": f"change:{p['id']}",
        "site": "Change",
        "url": change_org_petition_url(p.get("slug", "")),
        "title": clean_text(p.get("displayTitle") or p.get("ask")),
        "summary": clean_text(p.get("descriptionStripped") or p.get("description"), 150),
        "starter": org.get("name") or user.get("displayName") or "",
        "target": target,
        "start": (p.get("createdAt") or "")[:10],
        "end": "",
        "goal": goal,
        "photo": photo.split("?")[0],
        "count": count,
        "ended": p.get("status") != "PUBLISHED" or bool(p.get("victoryDate")),
    }


def fetch_by_url(url):
    """change.org か Voice の署名ページのURLから、署名の情報を読む。"""
    url = url.strip()
    m = re.search(r"voice\.charity/events/(\d+)", url)
    if m:
        d = fetch_voice_detail(m.group(1))
        d.update({"id": f"voice:{m.group(1)}", "site": "Voice"})
        return d
    if re.search(r"(change\.org|chng\.it)/", url):
        if not url.startswith("http"):
            url = "https://" + url
        return fetch_change_org_petition(url)
    raise ValueError("change.org か Voice（voice.charity）の署名ページのURLを入れてください")


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------

VOICE_QUERY = "q[title_or_organization_or_person_or_details_or_user_name_cont]"


def search_voice(keyword, full, known_max_id, title_only=False):
    """Voiceを検索する（1ページ50件・新しい順）。
    full=Falseなら、前回までに見た一番新しい番号より古いものが出てきたところで打ち切る。"""
    results = []
    page = 1
    while True:
        r = voice_get("https://voice.charity/events/search", params={VOICE_QUERY: keyword, "page": page})
        soup = BeautifulSoup(r.text, "html.parser")
        ids_on_page = []
        seen = set()
        for a in soup.select('a[href^="/events/"]'):
            m = re.match(r"^/events/(\d+)$", a.get("href", ""))
            if not m or m.group(1) in seen:
                continue
            card = a.find_parent("div", class_="card-height")
            if card is None:
                continue
            title_el = card.select_one(".card_title_size")
            if not title_el:
                continue
            event_id = m.group(1)
            seen.add(event_id)
            ids_on_page.append(int(event_id))
            title = title_el.get_text(strip=True)
            if title_only and keyword not in title:
                continue
            results.append({"id": f"voice:{event_id}", "event_id": int(event_id), "title": title})
        if not ids_on_page:
            break
        print(f"    Voice {page}ページ目（{len(ids_on_page)}件）")
        if not full and min(ids_on_page) <= known_max_id:
            break
        page += 1
    return results


def parse_voice_deadline(html_text):
    m = re.search(
        r'class="deadline">\s*(\d{4})\s*<span[^>]*>年</span>\s*(\d+)\s*<span[^>]*>月</span>\s*(\d+)',
        html_text,
    )
    if not m:
        return ""
    y, mo, d = map(int, m.groups())
    return date(y, mo, d).isoformat()


def fetch_voice_detail(event_id):
    """Voiceの署名ページから、提出先・作成者・本文・終了日・署名数などを読む。"""
    url = f"https://voice.charity/events/{event_id}"
    r = voice_get(url)
    t = r.text
    soup = BeautifulSoup(t, "html.parser")

    def span_after(label):
        for sp in soup.find_all("span"):
            txt = sp.get_text(strip=True)
            if txt.startswith(label):
                return txt[len(label):].strip()
        return ""

    title_el = soup.select_one(".show_title_small") or soup.select_one("h1.top_title")
    body_el = soup.select_one("#event_show")
    og = soup.find("meta", property="og:image")
    m = re.search(r'class="count">\s*([\d,]+)\s*<span class="count-text">\s*名', t)
    end = parse_voice_deadline(t)
    return {
        "url": url,
        "title": clean_text(title_el.get_text(" ")) if title_el else "",
        "summary": clean_text(re.sub(r"^\s*活動詳細", "", body_el.get_text("")) if body_el else "", 150),
        "starter": span_after("作成者："),
        "target": span_after("提出先："),
        "end": end,
        "photo": og["content"] if og and og.get("content") else "",
        "count": int(m.group(1).replace(",", "")) if m else None,
        "ended": bool(end) and end < date.today().isoformat(),
    }


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="署名運動の収集ツール")
    p.add_argument("--full", action="store_true", help="検索結果を最後のページまで全部見る（最初の1回用）")
    p.add_argument("--theme", action="append", help="テーマを絞る（keywords.jsonの名前。複数指定可）")
    p.add_argument("--skip-update", action="store_true", help="持っている署名の署名数更新をしない")
    p.add_argument("--dry-run", action="store_true", help="data.jsonに保存せず、結果を表示するだけ")
    return p.parse_args()


def new_item(base, theme, keyword, tag, today):
    item = {
        "id": base["id"],
        "site": base["site"],
        "url": base["url"],
        "title": base["title"] or "(タイトル不明)",
        "summary": base.get("summary", ""),
        "starter": base.get("starter", ""),
        "target": base.get("target", ""),
        "start": base.get("start", ""),
        "end": base.get("end", ""),
        "goal": base.get("goal"),
        "photo": base.get("photo", ""),
        "image": "",
        "tags": [tag],
        "keywords": [keyword],
        "pref": guess_pref(base["title"], base.get("target", "")),
        "status": "候補",
        "pick": False,
        "found": today,
        "counts": {},
    }
    if base.get("count") is not None:
        item["counts"][today] = base["count"]
    return item


def merge_keyword(item, keyword, tag):
    if keyword not in item["keywords"]:
        item["keywords"].append(keyword)
    if tag not in item["tags"]:
        item["tags"].append(tag)


def main():
    args = parse_args()
    themes = load_json(KEYWORDS_PATH, {})
    # この日より前に始まった署名は候補に入れない（開始日がわからないものは入れる）
    min_start = load_json(CONFIG_PATH, {}).get("min_start_date", "")
    too_old = lambda start: bool(min_start and start and start < min_start)
    if args.theme:
        unknown = set(args.theme) - set(themes)
        if unknown:
            print(f"警告: 知らないテーマ名を無視しました: {', '.join(unknown)}")
        themes = {k: v for k, v in themes.items() if k in args.theme}

    data = load_json(DATA_PATH, {"updated": "", "items": {}})
    items = data["items"]
    state = load_json(STATE_PATH, {"change_last_ts": 0, "voice_max_id": 0, "full_done": []})
    today = date.today().isoformat()
    run_started_ts = int(time.time())

    if not args.full and not items:
        print("data.json がまだ空です。最初の1回は `python collect.py --full` で全部集めてください。")
        sys.exit(1)

    def save():
        if args.dry_run:
            return
        data["updated"] = today
        save_json(DATA_PATH, data)

    # --- 1) 持っている署名の署名数を更新 ---
    if not args.skip_update:
        targets = [it for it in items.values() if it["status"] in TRACKED and today not in it["counts"]]
        print(f"持っている署名 {len(targets)} 件の署名数を確認しています...")
        failed = 0
        for n, it in enumerate(targets, 1):
            try:
                if it["site"] == "Change":
                    d = fetch_change_org_detail(it["url"])
                    time.sleep(0.5)
                else:
                    d = fetch_voice_detail(it["id"].split(":")[1])
                    if d["end"]:
                        it["end"] = d["end"]
            except requests.RequestException:
                failed += 1
                continue
            if d.get("count") is not None:
                it["counts"][today] = d["count"]
            if d.get("goal"):
                it["goal"] = d["goal"]
            if d["ended"]:
                it["status"] = "終了"
                print(f"  終了: {it['title'][:40]}")
            if n % 20 == 0:
                print(f"  {n}/{len(targets)} 件")
                save()
        save()
        print(f"  更新しました（取得できなかったもの {failed} 件）")

    # --- 2) 検索して新しい署名を探す ---
    api_key = None
    try:
        print("change.orgの検索用キーを取得しています...")
        api_key = get_change_org_api_key()
    except Exception as e:  # ブラウザが起動できない場合など
        print(f"  取得できませんでした: {e}")
    if not api_key:
        print("  警告: change.orgの検索はスキップします。")

    # 前回の実行より少し前（1週間）までさかのぼって見る（取りこぼし防止）
    since_ts = state["change_last_ts"] - 7 * 86400
    known_voice_max = state["voice_max_id"]
    voice_max_seen = known_voice_max
    added = []

    for theme_name, theme in themes.items():
        tag = theme["tag"]
        title_only = theme.get("title_only", False)
        for keyword in theme["keywords"]:
            done_key = f"{theme_name}/{keyword}"
            if args.full and done_key in state["full_done"]:
                print(f"「{keyword}」は全件取得が済んでいるので飛ばします")
                continue
            print(f"検索中: 「{theme_name}」/「{keyword}」")

            # change.org（検索結果だけで詳細までそろう）
            if api_key:
                try:
                    for base in search_change_org(keyword, api_key, args.full, since_ts, title_only):
                        if base["id"] in items:
                            merge_keyword(items[base["id"]], keyword, tag)
                            continue
                        if base["ended"] or too_old(base["start"]):
                            continue  # 終了したもの・古すぎるものは載せない
                        it = new_item(base, theme_name, keyword, tag, today)
                        items[it["id"]] = it
                        added.append(it)
                except requests.RequestException as e:
                    print(f"  change.org検索エラー: {e}")

            # Voice（新しいものだけ個別ページを開いて詳細を読む）
            try:
                for base in search_voice(keyword, args.full, known_voice_max, title_only):
                    voice_max_seen = max(voice_max_seen, base["event_id"])
                    if base["id"] in items:
                        merge_keyword(items[base["id"]], keyword, tag)
                        continue
                    try:
                        d = fetch_voice_detail(base["event_id"])
                    except requests.RequestException as e:
                        print(f"  Voice詳細エラー({base['event_id']}): {e}")
                        continue
                    if d["ended"] or too_old(d.get("start", "")):
                        continue  # 終了したもの・古すぎるものは載せない
                    d.update({"id": base["id"], "site": "Voice", "title": d["title"] or base["title"]})
                    it = new_item(d, theme_name, keyword, tag, today)
                    items[it["id"]] = it
                    added.append(it)
            except requests.RequestException as e:
                print(f"  Voice検索エラー: {e}")

            if args.full and not args.dry_run:
                state["full_done"].append(done_key)
                save_json(STATE_PATH, state)
            save()

    if not args.dry_run:
        state["change_last_ts"] = run_started_ts
        state["voice_max_id"] = voice_max_seen
        save_json(STATE_PATH, state)
        save()

    print("完了しました。")
    print(f"  新しい候補: {len(added)} 件")
    for it in added[:50]:
        print(f"    [{it['tags'][0]}] {it['title'][:50]}（{it['site']}）")
    if len(added) > 50:
        print(f"    ...ほか {len(added) - 50} 件")
    if args.dry_run:
        print("  （--dry-run のため保存していません）")
    else:
        print("次は `python review.py` で、載せる署名を選んでください。")


if __name__ == "__main__":
    main()
