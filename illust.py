"""しょめたんの絵から、ページで使うイラストを切り抜いて docs/illust/ に置く。

元の絵（「しょめたん」フォルダ）の一部を切り取り、まわりの背景を透明にして、
キャラクターと持ち物だけの画像（WebP）にする。絵を描き足すことはしない。
画像がまだ無いとき・元の絵やこのファイルが新しくなったときだけ作り直す（build.py が呼ぶ）。

使い方:  python illust.py        （全部作り直す）
"""
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "しょめたん"
OUT = HERE / "docs" / "illust"

# file  … 元の絵
# box   … 切り取る範囲（左, 上, 右, 下）。座標はすべて元の絵の中の位置
# keep  … 残すものの位置。そこにつながっている絵だけを残し、ふきだしや飾りは消す
# erase … 先に背景の色でぬりつぶす範囲（キャラクターにくっついているふきだしなど）
# width … 仕上がりの横幅（これより大きいときだけ縮める）
# fade  … 下のはしで切れている絵を、下に向かってうすくする
PARTS = {
    # ページ冒頭：署名用紙をかかえたしょめたん
    "hero": dict(file="地域.png", box=(20, 280, 680, 990), keep=[(350, 600)], width=640),
    # 探す：指さすしょめたん（虫めがねの loupe を重ねて search にする）
    "point": dict(file="４コマ_署名の理解.png", box=(60, 790, 545, 1104), keep=[(330, 960)], width=480, fade=True),
    "loupe": dict(file="民泊.png", box=(40, 494, 240, 650), keep=[(75, 545)], width=200),
    # 確かめる：「え？」と用紙を見るしょめたん
    "check": dict(file="４コマ_謎の鳥.png", box=(180, 540, 485, 815), keep=[(330, 690), (440, 585)], width=420),
    # 署名する：しょめたんの用紙に署名する鳥さん
    "sign": dict(file="４コマ_謎の鳥.png", box=(205, 880, 720, 1145), keep=[(360, 1030), (650, 1060)], width=560),
    # 署名したら：よろこぶしょめたん
    "thanks": dict(file="４コマ_謎の鳥.png", box=(200, 1225, 500, 1490), keep=[(345, 1380), (468, 1247), (486, 1276)],
                   erase=[(100, 1215, 273, 1266), (100, 1266, 262, 1300), (100, 1300, 250, 1334)], width=420),
    # 注意：おねがいするしょめたん
    "please": dict(file="１筆でも.png", box=(740, 320, 1440, 920), keep=[(1050, 600)],
                   erase=[(880, 300, 938, 368), (890, 368, 911, 388)], width=520),
    # 見つからない：「!?」のしょめたん
    "oops": dict(file="４コマ_不条理署名.png", box=(80, 1220, 400, 1485), keep=[(235, 1380), (318, 1245)], width=420),
}
# ページで使う画像の名前と、もとになる PARTS（icon は hero を小さくした、ページ左上のマーク）
OUTPUTS = {"hero": ["hero"], "search": ["point", "loupe"], "check": ["check"], "sign": ["sign"],
           "thanks": ["thanks"], "please": ["please"], "oops": ["oops"], "icon": ["hero"]}


def cut(file, box, keep, width, erase=(), fade=False):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.open(SRC / file).convert("RGB")
    px = np.asarray(img.crop(box)).astype(int)
    h, w = px.shape[:2]
    lo, hi = px.min(axis=-1), px.max(axis=-1)
    # 背景＝明るくて色の薄いところ（体の白＝ほぼ真っ白は背景にしない）
    light = (lo >= 185) & (lo < 247) & ((hi - lo) <= 40)
    ring = np.concatenate([px[0], px[-1], px[:, 0], px[:, -1]])
    ring_light = np.concatenate([light[0], light[-1], light[:, 0], light[:, -1]])
    base = np.median(ring[ring_light], axis=0)
    # さらに、ふちの背景の色に近いところだけにする（うすい紫の鳥などを消さないため）
    bg = light & (np.abs(px - base).max(axis=-1) <= 40)
    for x0, y0, x1, y1 in erase:
        bg[max(y0 - box[1], 0):max(y1 - box[1], 0), max(x0 - box[0], 0):max(x1 - box[0], 0)] = True
        px[max(y0 - box[1], 0):max(y1 - box[1], 0), max(x0 - box[0], 0):max(x1 - box[0], 0)] = base

    # 線のすき間から体の中まで背景あつかいにならないように、線を1ドット太らせてからたどる
    line = Image.fromarray(np.where(bg, 0, 255).astype("uint8")).filter(ImageFilter.MaxFilter(3))
    m = Image.fromarray(np.where(np.asarray(line) == 0, 255, 0).astype("uint8")).copy()
    # ふちから背景をたどって「外側」を見つける（線で囲まれた体の白い部分は残る）
    for x, y in [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)]:
        if m.getpixel((x, y)) == 255:
            ImageDraw.floodfill(m, (x, y), 128)
    outside = Image.fromarray(np.where(np.asarray(m) == 128, 255, 0).astype("uint8")).filter(ImageFilter.MaxFilter(3))

    # 残すものの位置につながっている絵だけを残す
    k = Image.fromarray(np.where(np.asarray(outside) == 0, 255, 0).astype("uint8")).copy()
    for sx, sy in keep:
        x, y = sx - box[0], sy - box[1]
        if k.getpixel((x, y)) != 255:
            # 指定した点がすき間なら、いちばん近い絵の点を使う
            ys, xs = np.nonzero(np.asarray(k) == 255)
            i = ((xs - x) ** 2 + (ys - y) ** 2).argmin()
            x, y = int(xs[i]), int(ys[i])
        ImageDraw.floodfill(k, (x, y), 200)
    alpha = Image.fromarray(np.where(np.asarray(k) == 200, 255, 0).astype("uint8")).filter(ImageFilter.GaussianBlur(0.7))
    a = np.asarray(alpha).astype(float)
    if fade:
        n = 40
        a[h - n:] *= np.linspace(1, 0, n)[:, None]
    out = Image.fromarray(np.dstack([px, a]).astype("uint8"), "RGBA")
    out = out.crop(out.getbbox())
    if out.width > width:
        out = out.resize((width, round(out.height * width / out.width)), Image.LANCZOS)
    return out


def build_search(body, loupe):
    """指さすしょめたんの左上に、虫めがねを重ねる。"""
    from PIL import Image

    lw = round(body.width * 0.34)
    loupe = loupe.resize((lw, round(loupe.height * lw / loupe.width)), Image.LANCZOS)
    pad = round(lw * 0.35)
    canvas = Image.new("RGBA", (body.width + pad, body.height + pad), (0, 0, 0, 0))
    canvas.alpha_composite(body, (pad, pad))
    canvas.alpha_composite(loupe, (0, 0))
    return canvas


def make_all(force=False):
    """足りない・古いイラストを作る。元の絵が無いものは飛ばす。"""
    from PIL import Image

    OUT.mkdir(parents=True, exist_ok=True)
    for name, part_names in OUTPUTS.items():
        out = OUT / f"{name}.webp"
        srcs = [SRC / PARTS[p]["file"] for p in part_names]
        if not all(s.exists() for s in srcs):
            continue
        newest = max([s.stat().st_mtime for s in srcs] + [Path(__file__).stat().st_mtime])
        if not force and out.exists() and out.stat().st_mtime >= newest:
            continue
        parts = [cut(**PARTS[p]) for p in part_names]
        img = build_search(*parts) if name == "search" else parts[0]
        if name == "icon":
            img = img.resize((96, round(img.height * 96 / img.width)), Image.LANCZOS)
        img.save(out, "WEBP", quality=88, method=6)
        print(f"  イラスト docs/illust/{name}.webp を作りました（{img.width}×{img.height}）")


def size_of(name):
    """ページに書く画像の大きさ（横, 縦）。"""
    from PIL import Image

    with Image.open(OUT / f"{name}.webp") as im:
        return im.size


if __name__ == "__main__":
    make_all(force=True)
