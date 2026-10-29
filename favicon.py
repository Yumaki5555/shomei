"""サイトのアイコン（ファビコン）を作って docs/ に置く。

パープルの地に、白い署名用紙とペン。文字や細かい飾りは入れない。
小さいアイコン（ブラウザのタブ用）は用紙とペンの形だけ、
大きいアイコン（スマホのホーム画面用）だけ、用紙に罫線を足す。

作るもの:  docs/favicon.svg（タブ用・どの大きさでもくっきり）
           docs/favicon.ico（SVG が使えないブラウザ用。16・32・48px）
           docs/apple-touch-icon.png（スマホのホーム画面用。180px）

デザインを変えたときだけ、手で実行する（build.py からは呼ばない）。
使い方:  python favicon.py
"""
import io
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "docs"

BRAND = "#7548a3"  # build.py の --brand と同じ色
LINE = "#cdb8e6"   # 用紙の罫線（大きいアイコンだけ）

# ペン：先が (0,0)、上へのびる形を、用紙の右下に45度かたむけて置く。
# 同じ形をパープルの太い線でふちどってから白でぬり、用紙と重なってもペンの形がわかるようにする。
PEN = "M0 0L-5.5-10V-31A5.5 5.5 0 0 1 5.5-31V-10Z"
PEN_AT = "translate(31 47) rotate(45)"


def svg(large=False, round_corner=True):
    """64×64 のアイコン。large=True で罫線を足す。round_corner=False は四角いまま（ホーム画面用。角はスマホが丸める）。"""
    rx = 14 if round_corner else 0
    lines = ""
    if large:
        lines = (f'<path d="M17 18H37M17 25H37M17 32H31" stroke="{LINE}" stroke-width="3" stroke-linecap="round"/>'
                 f'<path d="M16 50H27" stroke="{BRAND}" stroke-width="2.5" stroke-linecap="round"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            f'<rect width="64" height="64" rx="{rx}" fill="{BRAND}"/>'
            f'<rect x="11" y="9" width="31" height="45" rx="3.5" fill="#fff"/>'
            f'{lines}'
            f'<g transform="{PEN_AT}">'
            f'<path d="{PEN}" fill="{BRAND}" stroke="{BRAND}" stroke-width="5" stroke-linejoin="round"/>'
            f'<path d="{PEN}" fill="#fff"/>'
            f'</g></svg>')


def render(pages, svg_text, size):
    """SVG を、ブラウザ（Playwright）で size×size の PNG にする。"""
    from PIL import Image

    page = pages.new_page(viewport={"width": size, "height": size})
    page.set_content(f'<html><body style="margin:0">'
                     f'<div style="width:{size}px;height:{size}px">{svg_text.replace("<svg ", f"<svg width={size} height={size} ", 1)}</div>'
                     f'</body></html>')
    png = page.screenshot(omit_background=True)
    page.close()
    return Image.open(io.BytesIO(png)).convert("RGBA")


def main():
    from playwright.sync_api import sync_playwright

    small = svg()
    (OUT / "favicon.svg").write_text(small, encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ico = {n: render(browser, small, n) for n in (48, 32, 16)}
        touch = render(browser, svg(large=True, round_corner=False), 180)
        browser.close()
    ico[48].save(OUT / "favicon.ico", sizes=[(48, 48), (32, 32), (16, 16)], append_images=[ico[32], ico[16]])
    touch.convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    print("docs/favicon.svg・favicon.ico・apple-touch-icon.png を作りました")


if __name__ == "__main__":
    main()
