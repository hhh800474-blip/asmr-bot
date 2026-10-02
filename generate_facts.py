"""
مولّد فيديوهات "هل تعلم" عن فوائد الأكل (عربي، بصوت)
-----------------------------------------------------
1) يختار فاكهة/أكلة ما انعرضت قبل
2) Gemini يكتب السكربت (فوائد معروفة ومثبتة فقط)
3) Edge-TTS يقرا كل جملة بصوت عربي (نعرف توقيت كل جملة بالضبط)
4) Pixabay يجيب 3 صور للأكلة + زوم بطيء وانتقالات ناعمة
5) عناوين عربية بالأحمر والأصفر متزامنة ويا الصوت + موسيقى خفيفة

التشغيل: python generate_facts.py
الناتج:  output/<التاريخ>/video.mp4 + meta.json  (نفس اللي يقراه publish.py)
"""

import asyncio
import json
import os
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, features

os.environ["STYLE"] = "calm"   # موسيقى هادئة لهذا النوع
import generate_video as gv   # نستخدم منه: Gemini، Freesound، التحميل، السجل

log = gv.log
BASE = Path(__file__).parent
OUT_ROOT = BASE / "output"
W, H = 1080, 1920

PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()
FACTS_VOICE = os.getenv("FACTS_VOICE", "ar-SA-HamedNeural")   # صوت نسائي: ar-SA-ZariyahNeural
FACTS_MUSIC_VOLUME = float(os.getenv("FACTS_MUSIC_VOLUME", "0.10"))
PAGE_TAG = os.getenv("PAGE_TAG", "")   # نص صغير ثابت أسفل الشاشة (اختياري) مثل اسم الصفحة

# الاسم العربي : كلمة البحث بالإنجليزي : كلمات لازم تكون بوسوم الصورة
FOODS = [
    ("الشمام", "cantaloupe melon", ["melon", "cantaloupe"]),
    ("التين", "figs", ["fig", "figs"]),
    ("الرمان", "pomegranate", ["pomegranate"]),
    ("البرتقال", "oranges fruit", ["orange", "oranges"]),
    ("الموز", "bananas", ["banana", "bananas"]),
    ("التفاح", "red apples", ["apple", "apples"]),
    ("الفراولة", "strawberries", ["strawberry", "strawberries"]),
    ("العنب", "grapes", ["grape", "grapes"]),
    ("البطيخ", "watermelon", ["watermelon"]),
    ("المانجو", "mango fruit", ["mango", "mangoes"]),
    ("الكيوي", "kiwi fruit", ["kiwi"]),
    ("الأناناس", "pineapple", ["pineapple"]),
    ("التمر", "dates fruit", ["dates", "date"]),
    ("الأفوكادو", "avocado", ["avocado"]),
    ("الليمون", "lemons", ["lemon", "lemons"]),
    ("الجوز", "walnuts", ["walnut", "walnuts"]),
    ("اللوز", "almonds", ["almond", "almonds"]),
    ("الفستق", "pistachios", ["pistachio", "pistachios"]),
    ("الكرز", "cherries", ["cherry", "cherries"]),
    ("التوت الأزرق", "blueberries", ["blueberry", "blueberries"]),
    ("الخوخ", "peaches", ["peach", "peaches"]),
    ("المشمش", "apricots", ["apricot", "apricots"]),
    ("الجوافة", "guava", ["guava"]),
    ("جوز الهند", "coconut", ["coconut"]),
    ("البروكلي", "broccoli", ["broccoli"]),
    ("الجزر", "carrots", ["carrot", "carrots"]),
    ("الشمندر", "beetroot", ["beet", "beetroot", "beets"]),
    ("السبانخ", "spinach", ["spinach"]),
    ("الثوم", "garlic", ["garlic"]),
    ("الزنجبيل", "ginger root", ["ginger"]),
    ("الكركم", "turmeric", ["turmeric"]),
    ("العسل", "honey", ["honey"]),
    ("الشوفان", "oats", ["oats", "oatmeal"]),
    ("الحمص", "chickpeas", ["chickpeas", "chickpea"]),
    ("العدس", "lentils", ["lentils", "lentil"]),
    ("البيض", "eggs", ["egg", "eggs"]),
    ("زيت الزيتون", "olive oil", ["olive"]),
    ("الزيتون", "olives", ["olive", "olives"]),
    ("الطماطم", "tomatoes", ["tomato", "tomatoes"]),
    ("الخيار", "cucumber", ["cucumber"]),
    ("القرفة", "cinnamon", ["cinnamon"]),
    ("الكمثرى", "pears", ["pear", "pears"]),
    ("البرقوق", "plums", ["plum", "plums"]),
    ("القرنبيط", "cauliflower", ["cauliflower"]),
    ("الفلفل الحلو", "bell peppers", ["pepper", "peppers"]),
]


# ------------------------- الخط العربي -------------------------
def find_arabic_font():
    prefs = ["NotoKufiArabic-Bold", "NotoSansArabic-Bold", "NotoNaskhArabic-Bold",
             "Cairo", "Tajawal", "NotoSansArabic", "DejaVuSans-Bold"]
    try:
        out = subprocess.run(["fc-list", ":lang=ar", "file"], capture_output=True, text=True).stdout
        files = [l.split(":")[0].strip() for l in out.splitlines() if l.strip()]
    except Exception:
        files = []
    files += ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    for p in prefs:
        for f in files:
            if p.lower() in Path(f).name.lower() and Path(f).exists():
                return f
    return files[0] if files else None


FONT_PATH = find_arabic_font()
USE_RAQM = features.check("raqm")


def font(size):
    if USE_RAQM:
        return ImageFont.truetype(FONT_PATH, size, layout_engine=ImageFont.Layout.RAQM)
    return ImageFont.truetype(FONT_PATH, size)


def shape(text):
    """إذا ما كو raqm نستخدم arabic_reshaper + bidi حتى الحروف تتصل وتنقرا صح"""
    if USE_RAQM:
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def text_kw():
    return {"direction": "rtl", "language": "ar"} if USE_RAQM else {}


def measure(draw, text, f):
    b = draw.textbbox((0, 0), shape(text), font=f, **text_kw())
    return b[2] - b[0], b[3] - b[1], b


def wrap(draw, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if measure(draw, t, f)[0] <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_box_text(draw, text, f, cy, fg, bg, pad_x=40, pad_y=22, radius=22, stroke=0):
    tw, th, b = measure(draw, text, f)
    x0, y0 = (W - tw) / 2 - pad_x, cy - th / 2 - pad_y
    x1, y1 = (W + tw) / 2 + pad_x, cy + th / 2 + pad_y
    if bg:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=bg)
    draw.text(((W - tw) / 2 - b[0], cy - th / 2 - b[1]), shape(text), font=f, fill=fg,
              stroke_width=stroke, stroke_fill="black", **text_kw())
    return y1


def render_intro(name, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bottom = draw_box_text(d, "هل تعلم أن تناول", font(78), 1180, "white", (214, 31, 38, 245))
    draw_box_text(d, name, font(96), bottom + 95, (40, 10, 10), (255, 214, 0, 250))
    add_page_tag(d)
    img.save(path)


def render_fact(text, path, color=(255, 221, 0)):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font(80)
    lines = wrap(d, text, f, 900)
    y = 1220 - (len(lines) - 1) * 60
    for line in lines:
        tw, th, b = measure(d, line, f)
        # خلفية نص شفافة خفيفة حتى يبين على أي صورة
        d.rounded_rectangle([(W - tw) / 2 - 30, y - th / 2 - 18, (W + tw) / 2 + 30, y + th / 2 + 18],
                            radius=18, fill=(0, 0, 0, 110))
        d.text(((W - tw) / 2 - b[0], y - th / 2 - b[1]), shape(line), font=f, fill=color,
               stroke_width=5, stroke_fill="black", **text_kw())
        y += th + 50
    add_page_tag(d)
    img.save(path)


def add_page_tag(d):
    if PAGE_TAG:
        f = font(40)
        tw, th, b = measure(d, PAGE_TAG, f)
        d.text(((W - tw) / 2 - b[0], H - 230), shape(PAGE_TAG), font=f, fill=(255, 255, 255, 200),
               stroke_width=2, stroke_fill="black", **text_kw())


# ------------------------- السكربت -------------------------
def pick_food(history):
    used = history.setdefault("foods", [])
    fresh = [f for f in FOODS if f[0] not in used[-35:]]
    return random.choice(fresh or FOODS)


def write_script(name):
    prompt = f"""اكتب سكربت فيديو قصير (20-30 ثانية) لصفحة "هل تعلم" عن فوائد تناول {name}.
قواعد مهمة جداً:
- استخدم فقط معلومات غذائية معروفة ومتفق عليها (فيتامينات، ألياف، مضادات أكسدة، ترطيب، طاقة...).
- ممنوع تماماً ادعاء أنه يعالج أو يشفي أو يمنع أي مرض. استخدم كلمات مثل: يساعد، يدعم، غني بـ، مصدر جيد لـ.
- لا أرقام أو نسب مبالغ فيها، ولا كميات علاجية.
- عربية فصحى بسيطة وقريبة، جمل قصيرة وواضحة.
أرجع JSON فقط بهذه المفاتيح:
- intro_say: جملة تبدأ بـ "هل تعلم أن تناول {name}" (أقل من 12 كلمة) وتنتهي بسؤال يشد
- facts: قائمة من 3 عناصر، كل عنصر فيه:
    screen: نص الشاشة (3-6 كلمات)
    say: الجملة المنطوقة (8-16 كلمة)
- outro_say: جملة ختام قصيرة تطلب المتابعة (أقل من 8 كلمات)
- title: عنوان جذاب أقل من 60 حرف مع إيموجي واحد
- description: جملة واحدة
- hashtags: 5 هاشتاغات عربية"""
    res = gv.gemini_json(prompt)
    if not res or not res.get("facts"):
        raise RuntimeError("Gemini ما رجّع سكربت")
    res["facts"] = [f for f in res["facts"] if f.get("say") and f.get("screen")][:3]
    if not res["facts"]:
        raise RuntimeError("السكربت ناقص")
    res.setdefault("intro_say", f"هل تعلم أن تناول {name} مفيد جداً لجسمك؟")
    res.setdefault("outro_say", "تابعنا لمعرفة المزيد")
    res.setdefault("title", f"فوائد {name} 🍃")
    res.setdefault("description", f"أهم فوائد تناول {name}.")
    res.setdefault("hashtags", ["#هل_تعلم", "#فوائد", "#صحة", "#تغذية", "#معلومات"])
    return res


# ------------------------- الصوت -------------------------
def duration(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def tts_lines(lines, workdir):
    """كل جملة لوحدها حتى نعرف وقتها بالضبط، وبعدين نلصقهن"""
    import edge_tts
    wavs, durs = [], []
    for i, text in enumerate(lines):
        mp3 = workdir / f"line{i}.mp3"
        wav = workdir / f"line{i}.wav"
        asyncio.run(edge_tts.Communicate(text, FACTS_VOICE, rate="+5%").save(str(mp3)))
        gap = 0.35 if i < len(lines) - 1 else 0.8
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                        "-af", f"apad=pad_dur={gap}", "-ar", "44100", "-ac", "2", str(wav)], check=True)
        wavs.append(wav)
        durs.append(duration(wav))
    lst = workdir / "voice_list.txt"
    lst.write_text("".join(f"file '{w.name}'\n" for w in wavs), encoding="utf-8")
    voice = workdir / "voice.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(voice)], check=True, cwd=workdir)
    log(f"الصوت جاهز: {sum(durs):.1f} ثانية")
    return voice, durs


# ------------------------- الصور -------------------------
def get_images(query, must, history, workdir, n=3):
    if not PIXABAY_API_KEY:
        raise RuntimeError("PIXABAY_API_KEY مفقود")
    used = set(history.setdefault("pixabay_images", []))
    hits = []
    for orient in ("vertical", "all"):
        r = requests.get("https://pixabay.com/api/", timeout=30, params={
            "key": PIXABAY_API_KEY, "q": query, "image_type": "photo", "orientation": orient,
            "per_page": 80, "safesearch": "true", "order": "popular"})
        r.raise_for_status()
        for h in r.json().get("hits", []):
            tags = h.get("tags", "").lower()
            if h["id"] in used or not any(m in tags for m in must):
                continue
            if any(b in tags for b in ("woman", "man", "girl", "boy", "people", "person", "face")):
                continue
            hits.append(h)
        if len(hits) >= n:
            break
    if not hits:
        raise RuntimeError(f"ما لگينا صور لـ {query}")
    random.shuffle(hits)
    paths = []
    for i, h in enumerate(hits[:n]):
        p = workdir / f"img{i}.jpg"
        gv.download(h["largeImageURL"], p)
        paths.append(p)
        history["pixabay_images"].append(h["id"])
    log(f"صور: {len(paths)}")
    while len(paths) < n:           # إذا قليلة نعيد نفس الصورة بزوم مختلف
        paths.append(paths[len(paths) % max(1, len(paths))])
    return paths, ", ".join(dict.fromkeys(h["user"] for h in hits[:n]))


# ------------------------- التركيب -------------------------
def build(images, voice, durs, overlays, music, out):
    D = sum(durs)
    n = len(images)
    X = 0.5                                   # مدة الانتقال بين الصور
    L = D / n + X * (n - 1) / n               # طول كل صورة
    frames = int(L * 30) + 1

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for img in images:
        cmd += ["-i", str(img)]
    for ov, _, _ in overlays:
        cmd += ["-i", str(ov)]
    vi = n + len(overlays)
    cmd += ["-i", str(voice)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]

    parts = []
    for i in range(n):
        zin = random.choice([True, False])
        z = f"1+0.14*on/{frames}" if zin else f"1.14-0.14*on/{frames}"
        parts.append(
            f"[{i}:v]scale=1620:2880:force_original_aspect_ratio=increase,crop=1620:2880,"
            f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps=30,"
            f"eq=brightness=-0.04:contrast=1.06:saturation=1.15,trim=duration={L:.3f},"
            f"setpts=PTS-STARTPTS,setsar=1[i{i}]")
    cur = "[i0]"
    for k in range(1, n):
        off = k * (L - X)
        parts.append(f"{cur}[i{k}]xfade=transition=fade:duration={X}:offset={off:.3f}[x{k}]")
        cur = f"[x{k}]"
    for j, (_, a, b) in enumerate(overlays):
        parts.append(f"{cur}[{n + j}:v]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[o{j}]")
        cur = f"[o{j}]"
    parts.append(f"{cur}format=yuv420p[v]")

    fmt = "aformat=sample_rates=44100:channel_layouts=stereo"
    parts.append(f"[{vi}:a]{fmt},volume=1.25[vo]")
    if music:
        parts.append(f"[{vi + 1}:a]{fmt},volume={FACTS_MUSIC_VOLUME},afade=t=out:st={D - 1.2:.2f}:d=1.2[mu]")
        parts.append("[vo][mu]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.9[a]")
    else:
        parts.append("[vo]anull[a]")

    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]", "-t", f"{D:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    log(f"الفيديو جاهز: {out} ({D:.1f} ثانية)")


# ------------------------- التشغيل الرئيسي -------------------------
def main():
    log(f"الخط: {FONT_PATH} | raqm={USE_RAQM}")
    history = gv.load_history()
    workdir = OUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    workdir.mkdir(parents=True, exist_ok=True)

    name, query, must = pick_food(history)
    log(f"الموضوع: {name}")
    script = write_script(name)

    lines = [script["intro_say"]] + [f["say"] for f in script["facts"]] + [script["outro_say"]]
    voice, durs = tts_lines(lines, workdir)

    # توقيت كل نص على الشاشة = توقيت جملته بالصوت
    overlays, t = [], 0.0
    intro_png = workdir / "ov_intro.png"
    render_intro(name, intro_png)
    overlays.append((intro_png, 0, durs[0]))
    t = durs[0]
    for i, f in enumerate(script["facts"]):
        p = workdir / f"ov_fact{i}.png"
        render_fact(f["screen"], p)
        overlays.append((p, t, t + durs[i + 1]))
        t += durs[i + 1]
    out_png = workdir / "ov_outro.png"
    render_fact("تابعنا للمزيد", out_png, color=(255, 255, 255))
    overlays.append((out_png, t, t + durs[-1]))

    images, author = get_images(query, must, history, workdir, n=3)
    music, music_credit = gv.get_music(history, workdir) if gv.MUSIC_ENABLED else (None, None)
    video = workdir / "video.mp4"
    build(images, voice, durs, overlays, music, video)

    credits = f"\n\nصور: {author} (Pixabay)"
    if music_credit:
        credits += f"\nموسيقى: {music_credit['author']} (Freesound)"
    credits += "\nالصوت مولّد بالذكاء الاصطناعي. معلومات عامة وليست نصيحة طبية."
    meta = {
        "title": script["title"][:100],
        "description": script["description"] + "\n\n" + " ".join(script["hashtags"]) + credits,
        "hashtags": script["hashtags"],
        "video_file": str(video),
        "ai_voice": True,
        "ai_generated": True,
        "topic": name,
        "created_at": datetime.now().isoformat(),
    }
    (workdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    for f in workdir.iterdir():
        if f.name not in ("video.mp4", "meta.json"):
            f.unlink()

    history.setdefault("foods", []).append(name)
    history.setdefault("titles", []).append(script["title"])
    gv.save_history(history)
    log("✅ خلصنا")
    return meta


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ فشل: {e}")
        sys.exit(1)
