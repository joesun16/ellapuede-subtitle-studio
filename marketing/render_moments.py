"""Render the nine EllaPuede 0.14.4 WeChat Moments cards.

Run on macOS with Pillow and OpenCV installed. The exported PNGs are the
portable deliverables; this source remains editable for future releases.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import math

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "moments-0.14.4"
OUT.mkdir(parents=True, exist_ok=True)
S = 2
W = H = 1080
GREEN = "#0D6256"
DEEP = "#073D37"
INK = "#15312C"
MUTED = "#5B736B"
MINT = "#CDEBDD"
CREAM = "#F7F7F0"
WHITE = "#FFFFFF"
LINE = "#D8E3D9"
URL = "https://github.com/joesun16/ellapuede-subtitle-studio"


@lru_cache(maxsize=None)
def font(size: int, bold: bool = False, latin: bool = False) -> ImageFont.FreeTypeFont:
    if latin:
        path = "/System/Library/Fonts/HelveticaNeue.ttc"
        return ImageFont.truetype(path, size * S, index=1 if bold else 0)
    path = "/System/Library/Fonts/Hiragino Sans GB.ttc"
    return ImageFont.truetype(path, size * S, index=2 if bold else 0)


def xy(box):
    return tuple(round(v * S) for v in box)


def color(hex_color: str):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def gradient(top: str, bottom: str) -> Image.Image:
    a, b = np.array(color(top), dtype=np.float32), np.array(color(bottom), dtype=np.float32)
    y = np.linspace(0, 1, H * S, dtype=np.float32)[:, None, None]
    rgb = np.broadcast_to((a * (1 - y) + b * y).astype(np.uint8), (H * S, W * S, 3)).copy()
    return Image.fromarray(rgb, "RGB")


def roundrect(d: ImageDraw.ImageDraw, box, radius: int, fill, outline=None, width: int = 1):
    d.rounded_rectangle(xy(box), radius=radius * S, fill=fill, outline=outline, width=width * S)


def line(d: ImageDraw.ImageDraw, points, fill, width=2):
    d.line([xy(p) for p in points], fill=fill, width=width * S, joint="curve")


def text(d: ImageDraw.ImageDraw, x, y, value, size=40, fill=INK, bold=False, latin=False, spacing=1.18):
    for i, segment in enumerate(value.split("\n")):
        d.text(xy((x, y + i * size * spacing)), segment, font=font(size, bold, latin), fill=fill)


def center_text(d, cx, y, value, size=40, fill=INK, bold=False, latin=False):
    f = font(size, bold, latin)
    box = d.textbbox((0, 0), value, font=f)
    d.text(xy((cx, y)), value, font=f, fill=fill, anchor="mt")


def circle(d, cx, cy, r, fill, outline=None, width=2):
    d.ellipse(xy((cx - r, cy - r, cx + r, cy + r)), fill=fill, outline=outline, width=width * S)


def pill(d, x, y, label, fill=MINT, ink=DEEP, width=None, height=52, size=25):
    f = font(size, True)
    measured = d.textlength(label, font=f) / S
    width = width or int(measured + 36)
    roundrect(d, (x, y, x + width, y + height), height // 2, fill)
    d.text(xy((x + width / 2, y + height / 2)), label, font=f, fill=ink, anchor="mm")
    return width


def halo(img: Image.Image, x, y, radius, fill, alpha=80):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.ellipse(xy((x - radius, y - radius, x + radius, y + radius)), fill=(*color(fill), alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius * S // 2))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))


def footer(d, n, dark=False):
    col = "#ACD7C4" if dark else MUTED
    line(d, [(78, 991), (1002, 991)], col, 1)
    text(d, 80, 1013, "EllaPuede · 字幕提取工具", 22, col, latin=False)
    text(d, 900, 1013, f"{n:02d} / 09", 21, col, latin=True)


def tab(d, label, n, dark=False):
    c = "#CDEBDD" if dark else GREEN
    roundrect(d, (80, 72, 132, 110), 12, c)
    center_text(d, 106, 78, str(n), 24, DEEP if dark else WHITE, True, True)
    text(d, 151, 77, label.upper(), 21, c if dark else MUTED, True, True)


def file_icon(d, x, y, ext, filename, fill=WHITE, outline=LINE):
    roundrect(d, (x, y, x + 300, y + 290), 23, fill, outline, 2)
    roundrect(d, (x + 31, y + 32, x + 122, y + 126), 18, "#E1F2E9")
    center_text(d, x + 76, y + 51, ext, 30, GREEN, True, True)
    text(d, x + 32, y + 159, filename, 31, INK, True)
    line(d, [(x + 32, y + 222), (x + 251, y + 222)], LINE, 2)
    line(d, [(x + 32, y + 247), (x + 193, y + 247)], LINE, 2)


def card1():
    im = gradient("#063A37", "#0B6B5D")
    halo(im, 920, 120, 320, "#59B18A", 90)
    d = ImageDraw.Draw(im)
    tab(d, "FROM FRAME TO FILE", 1, True)
    text(d, 80, 154, "把画面里的对白，\n变成字幕文件。", 78, WHITE, True, spacing=1.32)
    text(d, 83, 390, "从视频字幕到可用的 SRT / ASS", 34, "#D8EEE2")
    roundrect(d, (80, 535, 640, 885), 28, "#123B39", "#60AA92", 2)
    roundrect(d, (107, 565, 613, 836), 14, "#1A4441")
    circle(d, 250, 675, 86, "#295751")
    circle(d, 492, 682, 106, "#315D54")
    roundrect(d, (155, 744, 561, 808), 13, "#0F2928", "#A7D7BF", 2)
    center_text(d, 358, 761, "I’m so sorry.", 32, WHITE, True, True)
    line(d, [(658, 705), (716, 705)], "#A5DCC0", 6)
    line(d, [(697, 687), (716, 705), (697, 722)], "#A5DCC0", 6)
    roundrect(d, (741, 599, 991, 814), 23, "#F2FBF4")
    text(d, 776, 632, "第01集", 31, INK, True)
    text(d, 776, 707, ".srt", 58, GREEN, True, True)
    pill(d, 80, 916, "0.14.4 开源公测", "#D7EBDD", DEEP, size=22)
    footer(d, 1, True)
    return im


def card2():
    im = gradient(CREAM, "#EAF2E9")
    d = ImageDraw.Draw(im)
    tab(d, "THE PROBLEM", 2)
    text(d, 80, 160, "视频里有字幕，\n却没有字幕文件？", 74, INK, True, spacing=1.36)
    text(d, 82, 386, "手工处理一整部剧，总是在重复：", 32, MUTED)
    for i, (num, phrase) in enumerate([("01", "逐句截图与抄写"), ("02", "手动对时间轴"), ("03", "每集重复找字幕位置")]):
        y = 472 + i * 112
        roundrect(d, (80, y, 1000, y + 88), 20, WHITE, LINE, 1)
        circle(d, 132, y + 44, 27, "#E9F3EC")
        center_text(d, 132, y + 29, num, 22, GREEN, True, True)
        text(d, 189, y + 18, phrase, 36, INK, True)
    roundrect(d, (80, 855, 1000, 946), 22, GREEN)
    text(d, 109, 880, "把重复劳动交给同一条处理流程。", 33, WHITE, True)
    footer(d, 2)
    return im


def card3():
    im = gradient("#DFEFE4", "#F8FAF4")
    d = ImageDraw.Draw(im)
    tab(d, "ONE REGION / WHOLE SERIES", 3)
    text(d, 80, 162, "框一次，\n整剧共用。", 88, INK, True, spacing=1.34)
    text(d, 83, 422, "字幕位置相同的剧集，不必逐集重选。", 31, MUTED)
    roundrect(d, (80, 535, 556, 908), 26, WHITE, LINE, 2)
    text(d, 113, 565, "剧集队列", 29, GREEN, True)
    for i in range(3):
        y = 625 + i * 82
        roundrect(d, (112, y, 525, y + 65), 13, "#F0F6F0")
        circle(d, 151, y + 32, 17, GREEN)
        line(d, [(142, y + 32), (149, y + 39), (161, y + 25)], WHITE, 3)
        text(d, 188, y + 14, f"第{i + 1:02d}集.mp4", 30, INK, True)
    text(d, 112, 865, "同一个对白区域", 27, GREEN, True)
    line(d, [(559, 714), (620, 714)], GREEN, 6)
    line(d, [(601, 696), (620, 714), (601, 731)], GREEN, 6)
    roundrect(d, (645, 540, 1000, 909), 24, "#173D3A")
    circle(d, 822, 695, 130, "#305B54")
    roundrect(d, (671, 768, 973, 841), 5, None, "#86E4B3", 5)
    center_text(d, 822, 783, "Hello again.", 29, WHITE, True, True)
    footer(d, 3)
    return im


def card4():
    im = gradient(WHITE, CREAM)
    d = ImageDraw.Draw(im)
    tab(d, "DIALOGUE ONLY", 4)
    text(d, 80, 160, "只取对白，\n不扫整张画面。", 76, INK, True, spacing=1.34)
    text(d, 83, 384, "手动框选是主路径；自动定位可主动选择。", 29, MUTED)
    roundrect(d, (86, 483, 994, 873), 26, "#183E3B")
    roundrect(d, (110, 506, 970, 849), 15, "#244943")
    text(d, 147, 548, "画面标题", 38, "#90A79C", True)
    text(d, 757, 572, "水印", 30, "#91A69D")
    circle(d, 485, 676, 95, "#3C665B")
    circle(d, 646, 680, 78, "#537569")
    roundrect(d, (161, 750, 920, 826), 10, "#102D2B", "#81E1AF", 4)
    center_text(d, 540, 760, "这句对白才是要导出的字幕", 32, WHITE, True)
    pill(d, 84, 902, "对白区域 OCR", "#DDF0E2", DEEP, size=25)
    footer(d, 4)
    return im


def card5():
    im = gradient("#074D45", "#0B7868")
    halo(im, 540, 510, 350, "#52B48E", 70)
    d = ImageDraw.Draw(im)
    roundrect(d, (300, 145, 780, 915), 42, "#F5FBF4")
    icon = Image.open(Path(__file__).resolve().parents[1] / "assets/app-icon.png").convert("RGBA")
    icon = icon.resize((232 * S, 232 * S), Image.Resampling.LANCZOS)
    im.paste(icon, xy((424, 230)), icon)
    d = ImageDraw.Draw(im)
    center_text(d, 540, 510, "EllaPuede", 76, DEEP, True, True)
    center_text(d, 540, 616, "字幕提取工具", 58, GREEN, True)
    line(d, [(386, 722), (694, 722)], "#A9CDB7", 2)
    center_text(d, 540, 759, "0.14.4  ·  开源公测", 27, MUTED, True)
    footer(d, 5, True)
    return im


def card6():
    im = gradient("#F6F8F2", "#E5F1E7")
    d = ImageDraw.Draw(im)
    tab(d, "EXPORT WHAT YOU NEED", 6)
    text(d, 80, 160, "SRT 或 ASS，\n由你来选。", 82, INK, True, spacing=1.36)
    text(d, 84, 398, "也可以两种格式一起导出。", 32, MUTED)
    file_icon(d, 100, 513, "SRT", "第01集.srt")
    file_icon(d, 680, 513, "ASS", "第01集.ass")
    line(d, [(438, 656), (644, 656)], GREEN, 6)
    circle(d, 540, 656, 31, GREEN)
    center_text(d, 540, 637, "+", 35, WHITE, True, True)
    roundrect(d, (80, 860, 1000, 946), 20, "#DDF0E3")
    text(d, 111, 883, "导出文件名，与原视频文件名对齐。", 32, GREEN, True)
    footer(d, 6)
    return im


def card7():
    im = gradient("#E3F1E8", "#F7F8F3")
    d = ImageDraw.Draw(im)
    tab(d, "SOURCE LANGUAGE", 7)
    text(d, 80, 160, "按原字幕语言，\n选择识别路线。", 76, INK, True, spacing=1.34)
    text(d, 83, 385, "按原字幕语言选择对应识别路线。", 31, MUTED)
    labels = [("英语", 110, 510, 290), ("简体中文", 415, 510, 355),
              ("繁體中文", 110, 615, 355), ("日本語", 480, 615, 280),
              ("韩语", 110, 720, 290), ("泰语", 415, 720, 290)]
    for i, (label, x, y, w) in enumerate(labels):
        roundrect(d, (x, y, x + w, y + 76), 20, WHITE, "#C4DCCB", 2)
        circle(d, x + 36, y + 38, 9, GREEN if i % 2 == 0 else "#80B797")
        text(d, x + 66, y + 18, label, 31, INK, True)
    text(d, 111, 850, "另可选西 / 法 / 德 / 葡 / 意语及中英双语", 27, MUTED)
    text(d, 111, 901, "自动判断目前主要覆盖中、英、韩。", 26, GREEN, True)
    footer(d, 7)
    return im


def card8():
    im = gradient(WHITE, "#EDF5ED")
    d = ImageDraw.Draw(im)
    tab(d, "OFFLINE · CROSS PLATFORM", 8)
    text(d, 80, 162, "安装即用，\n在本地处理。", 84, INK, True, spacing=1.34)
    text(d, 83, 409, "安装包内置 OCR 模型和运行时。", 31, MUTED)
    roundrect(d, (87, 525, 992, 875), 25, "#0F514A")
    roundrect(d, (145, 595, 449, 777), 23, "#F4FAF4")
    roundrect(d, (551, 595, 855, 777), 23, "#F4FAF4")
    center_text(d, 297, 638, "macOS", 48, DEEP, True, True)
    center_text(d, 703, 638, "Windows", 45, DEEP, True, True)
    center_text(d, 297, 719, "Apple Silicon", 27, MUTED, False, True)
    center_text(d, 703, 719, "x64", 30, MUTED, False, True)
    line(d, [(464, 682), (536, 682)], "#CBE8D5", 4)
    text(d, 146, 812, "视频不需上传云端 · 识别时无需联网", 30, WHITE, True)
    footer(d, 8)
    return im


def card9():
    im = gradient("#083F3A", "#0A685C")
    halo(im, 1000, 870, 290, "#6AC994", 80)
    d = ImageDraw.Draw(im)
    tab(d, "OPEN BETA", 9, True)
    text(d, 80, 159, "开源公测，\n现在就试。", 88, WHITE, True, spacing=1.33)
    text(d, 83, 420, "免费使用 · 可查看源码 · 欢迎反馈", 31, "#CDE9D9")
    roundrect(d, (78, 522, 1002, 908), 26, "#F6FBF5")
    text(d, 112, 560, "GitHub 下载", 38, GREEN, True)
    text(d, 112, 633, "github.com/joesun16/", 28, INK, False, True)
    text(d, 112, 681, "ellapuede-subtitle-studio", 26, INK, True, True)
    text(d, 112, 773, "0.14.4 公测版", 26, MUTED, True)
    text(d, 112, 814, "请按系统选择安装包", 26, MUTED)
    qr = cv2.QRCodeEncoder_create().encode(URL)
    qr_im = Image.fromarray(qr).convert("L")
    qr_im = qr_im.resize((232 * S, 232 * S), Image.Resampling.NEAREST)
    im.paste(qr_im.convert("RGB"), xy((735, 584)))
    footer(ImageDraw.Draw(im), 9, True)
    return im


def github_cover():
    im = Image.new("RGB", (1600 * S, 560 * S), DEEP)
    d = ImageDraw.Draw(im)
    d.ellipse(xy((1120, -260, 1820, 440)), fill="#176B5D")
    d.ellipse(xy((1270, 200, 1740, 670)), fill="#247665")
    icon = Image.open(Path(__file__).resolve().parents[1] / "assets/app-icon.png").convert("RGBA")
    icon = icon.resize((168 * S, 168 * S), Image.Resampling.LANCZOS)
    im.paste(icon, xy((88, 166)), icon)
    d = ImageDraw.Draw(im)
    pill(d, 307, 80, "OPEN SOURCE  ·  0.14.4 BETA", "#CFE9DA", DEEP, size=23)
    text(d, 305, 177, "EllaPuede", 86, WHITE, True, True)
    text(d, 311, 306, "从画面对白，到同名字幕文件。", 43, "#D6EEE0", True)
    for x, label in ((310, "整剧共用区域"), (546, "离线 OCR"), (742, "SRT / ASS")):
        width = 202 if label == "整剧共用区域" else 159 if label == "离线 OCR" else 170
        roundrect(d, (x, 438, x + width, 489), 16, "#175E53", "#3B8774", 1)
        center_text(d, x + width / 2, 447, label, 25, WHITE, True)
    roundrect(d, (1136, 180, 1458, 371), 20, "#F1FAF2")
    text(d, 1171, 220, "第01集.srt", 38, GREEN, True)
    text(d, 1171, 287, "第01集.ass", 38, GREEN, True)
    return im.resize((1600, 560), Image.Resampling.LANCZOS)


def main():
    cards = [fn() for fn in (card1, card2, card3, card4, card5, card6, card7, card8, card9)]
    for n, image in enumerate(cards, 1):
        image.resize((W, H), Image.Resampling.LANCZOS).save(OUT / f"{n:02d}.png", optimize=True)
    gap = 20
    width = W * 3 + gap * 4
    sheet = Image.new("RGB", (width, width), "#DFE8E0")
    for i, image in enumerate(cards):
        x = gap + (i % 3) * (W + gap)
        y = gap + (i // 3) * (H + gap)
        sheet.paste(image.resize((W, H), Image.Resampling.LANCZOS), (x, y))
    sheet.save(OUT / "九宫格总览.png", optimize=True)
    github_cover().save(ROOT / "GitHub-cover.png", optimize=True)
    detector = cv2.QRCodeDetector()
    qr_card = cv2.imread(str(OUT / "09.png"))
    decoded, _, _ = detector.detectAndDecode(qr_card)
    assert decoded == URL, f"QR did not decode: {decoded!r}"
    print(f"Rendered 9 cards and contact sheet to {OUT}")


if __name__ == "__main__":
    main()
