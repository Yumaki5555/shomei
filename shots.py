"""「掲載」にした署名のうち、まだスクショが無いものだけ撮る。

スクショは docs/img/ に、横幅600pxの小さめのJPEGで保存する。

使い方:  python shots.py        （publish.py からも自動で呼ばれる）
         python shots.py --redo （掲載中の全部を撮り直す）
"""
import argparse
from pathlib import Path

from collect import DATA_PATH, UA, load_json, save_json

HERE = Path(__file__).parent
IMG_DIR = HERE / "docs" / "img"


def main(redo=False):
    data = load_json(DATA_PATH, {"items": {}})
    targets = [it for it in data["items"].values()
               if it["status"] == "掲載" and (redo or not it.get("image") or not (HERE / "docs" / it["image"]).exists())]
    if not targets:
        print("新しく撮るスクショはありません")
        return
    print(f"スクショを {len(targets)} 件撮ります...")

    from playwright.sync_api import sync_playwright

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA, viewport={"width": 600, "height": 800}, locale="ja-JP")
        for it in targets:
            name = it["id"].replace(":", "-") + ".jpg"
            try:
                page.goto(it["url"], wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)  # 画像などが出そろうのを少し待つ
                # クッキーの確認など、画面をふさぐ表示があれば隠す
                page.add_style_tag(content="[id*=cookie],[class*=cookie],[class*=Cookie],[id*=onetrust]{display:none!important}")
                page.screenshot(path=str(IMG_DIR / name), type="jpeg", quality=60)
            except Exception as e:  # 1件失敗しても残りは続ける
                print(f"  失敗: {it['title'][:40]}（{e.__class__.__name__}）")
                continue
            it["image"] = f"img/{name}"
            ok += 1
            print(f"  撮影: {it['title'][:40]}")
        browser.close()
    save_json(DATA_PATH, data)
    print(f"スクショを {ok} 件保存しました")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--redo", action="store_true", help="掲載中の全部を撮り直す")
    main(ap.parse_args().redo)
