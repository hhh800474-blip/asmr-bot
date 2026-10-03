"""
مولّد فيديوهات قناة "لمحة": معلومة سريعة بالعربي (≤ 15 ثانية)
-------------------------------------------------------------
1) يختار مجال بالتناوب (صحة، رياضة، جسم الإنسان، نفس، فضاء، حيوانات...)
2) Gemini يختار موضوع جديد ويكتب معلومة صحيحة وبداية مختلفة كل مرة
3) صوت عربي يتبدل كل مرة: بنت / شاب
4) لقطات فيديو + صور من Pixabay مخلوطة، بزوم وانتقالات ناعمة
5) عنوان أحمر/أصفر + نصوص متزامنة ويا الصوت + لوكو #لمحة ثابت بالزاوية

التشغيل: python generate_facts.py
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
MAX_SECONDS = float(os.getenv("MAX_SECONDS", "15"))
LOGO_TEXT = os.getenv("LOGO_TEXT", "#لمحة")
FACTS_MUSIC_VOLUME = float(os.getenv("FACTS_MUSIC_VOLUME", "0.10"))
# الأصوات تتبدل بالترتيب: شاب، بنت، شاب، بنت...
VOICES = [v.strip() for v in os.getenv(
    "FACTS_VOICES", "ar-SA-HamedNeural,ar-SA-ZariyahNeural,ar-AE-HamdanNeural,ar-AE-FatimaNeural"
).split(",") if v.strip()]

CATEGORIES = [
    "صحة وعادات يومية", "رياضة ولياقة", "جسم الإنسان", "علم النفس والسلوك", "النوم",
    "تغذية وفوائد الأكل", "الفضاء والكون", "عالم الحيوان", "الطبيعة والأرض",
    "علوم مدهشة", "الدماغ والذاكرة", "الماء والترطيب",
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


AR_DIGITS = str.maketrans("0123456789%", "٠١٢٣٤٥٦٧٨٩٪")


def latin_font(size):
    for f in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def shape(text):
    text = text.translate(AR_DIGITS).replace("#", "")
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


def render_intro(top, main, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bottom = draw_box_text(d, top, font(74), 1160, "white", (214, 31, 38, 245))
    lines = wrap(d, main, font(92), 920)
    y = bottom + 90
    for line in lines[:2]:
        y = draw_box_text(d, line, font(92), y, (40, 10, 10), (255, 214, 0, 250)) + 85
    img.save(path)


def render_fact(text, path, color=(255, 221, 0)):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font(80)
    lines = wrap(d, text, f, 900)
    y = 1220 - (len(lines) - 1) * 60
    for line in lines:
        tw, th, b = measure(d, line, f)
        d.rounded_rectangle([(W - tw) / 2 - 30, y - th / 2 - 18, (W + tw) / 2 + 30, y + th / 2 + 18],
                            radius=18, fill=(0, 0, 0, 120))
        d.text(((W - tw) / 2 - b[0], y - th / 2 - b[1]), shape(line), font=f, fill=color,
               stroke_width=5, stroke_fill="black", **text_kw())
        y += th + 50
    img.save(path)


def render_logo(path):
    """لوكو #لمحة ثابت بالزاوية العليا اليمين (العلامة # بخط لاتيني حتى ما تطلع مربع)"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    word = LOGO_TEXT.replace("#", "").strip()
    f, fh = font(58), latin_font(52)
    tw, th, b = measure(d, word, f)
    hb = d.textbbox((0, 0), "#", font=fh)
    hw = hb[2] - hb[0]
    gap = 6
    x1, y0 = W - 50, 250
    inner = tw + (hw + gap if "#" in LOGO_TEXT else 0)
    x0, y1 = x1 - inner - 56, y0 + th + 36
    d.rounded_rectangle([x0, y0, x1, y1], radius=(y1 - y0) // 2, fill=(214, 31, 38, 225))
    cy = (y0 + y1) / 2
    # بالعربي العلامة تجي يمين الكلمة: #لمحة
    if "#" in LOGO_TEXT:
        d.text((x1 - 28 - hw - hb[0], cy - (hb[3] - hb[1]) / 2 - hb[1]), "#", font=fh, fill="white")
    d.text((x0 + 28 - b[0], cy - th / 2 - b[1]), shape(word), font=f, fill="white", **text_kw())
    img.save(path)


# ------------------------- السكربت -------------------------
def write_script(history):
    cats = history.setdefault("fact_categories", [])
    cat = next((c for c in random.sample(CATEGORIES, len(CATEGORIES)) if c not in cats[-6:]),
               random.choice(CATEGORIES))
    topics = history.setdefault("fact_topics", [])[-60:]
    openings = history.setdefault("fact_openings", [])[-12:]
    prompt = f"""أنت كاتب لقناة "لمحة" التي تنشر معلومة سريعة ومدهشة بالعربي في فيديو قصير جداً (أقل من 15 ثانية).
المجال هذه المرة: {cat}
اختر موضوعاً محدداً جديداً داخل هذا المجال، مختلفاً عن هذه المواضيع السابقة: {topics}

قواعد الدقة (مهمة جداً):
- معلومات صحيحة ومعروفة علمياً فقط. إذا لم تكن متأكداً فاختر موضوعاً آخر.
- ممنوع ادعاء أن شيئاً يعالج أو يشفي أو يمنع مرضاً. استخدم: يساعد، يدعم، قد، يرتبط بـ.
- لا أرقام مبالغ فيها.

قواعد الأسلوب:
- البداية يجب أن تكون مختلفة تماماً عن هذه البدايات السابقة: {openings}
- لا تبدأ بـ "هل تعلم". نوّع: سؤال مفاجئ، رقم مدهش، "تخيل أن..."، معلومة صادمة، "لماذا..."، "سر..."، تحدي، مقارنة.
- عربية فصحى بسيطة وجمل قصيرة جداً. لا تطلب المتابعة ولا الاشتراك.

أرجع JSON فقط:
- topic: الموضوع بكلمتين
- headline_top: سطر علوي قصير (2-4 كلمات) يناسب البداية، مثل "سر لا يعرفه كثيرون" أو "لماذا يحدث"
- headline_main: الكلمة الأساسية للموضوع (1-3 كلمات)
- intro_say: جملة البداية المنطوقة (5-9 كلمات)
- facts: قائمة من عنصرين، كل عنصر: screen (3-6 كلمات للشاشة) و say (6-11 كلمة منطوقة)
- pixabay_query: كلمتان بالإنجليزية تصف بالضبط المشهد اللي تتكلم عنه المعلومة (مو الموضوع العام).
  مثال: معلومة عن جبال تحت البحر = "underwater ocean" مو "mountains". شيء ملموس وبدون وجوه.
- title: عنوان أقل من 60 حرف مع إيموجي واحد
- description: جملة واحدة
- hashtags: 4 هاشتاغات عربية"""
    res = gv.gemini_json(prompt)
    if not res or not res.get("facts") or not res.get("intro_say"):
        raise RuntimeError("Gemini ما رجّع سكربت")
    res["facts"] = [f for f in res["facts"] if f.get("say") and f.get("screen")][:2]
    if not res["facts"]:
        raise RuntimeError("السكربت ناقص")
    res.setdefault("topic", cat)
    res.setdefault("headline_top", "معلومة سريعة")
    res.setdefault("headline_main", res["topic"])
    res.setdefault("pixabay_query", "nature")
    res.setdefault("title", f"{res['topic']} ✨")
    res.setdefault("description", res["intro_say"])
    tags = [t if t.startswith("#") else "#" + t.replace(" ", "_") for t in res.get("hashtags", [])][:4]
    res["hashtags"] = [LOGO_TEXT] + [t for t in tags if t != LOGO_TEXT]
    res["category"] = cat
    log(f"المجال: {cat} | الموضوع: {res['topic']} | البداية: {res['intro_say']}")
    return res


# ------------------------- الصوت -------------------------
def duration(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def pick_voice(history):
    i = history.get("voice_counter", [0])
    i = i[0] if isinstance(i, list) and i else 0
    history["voice_counter"] = [i + 1]
    return VOICES[i % len(VOICES)]


def tts_lines(lines, voice, workdir):
    """كل جملة لوحدها حتى نعرف وقتها بالضبط"""
    import edge_tts
    raw = []
    for i, text in enumerate(lines):
        mp3 = workdir / f"line{i}.mp3"
        asyncio.run(edge_tts.Communicate(text, voice, rate="+8%").save(str(mp3)))
        raw.append(mp3)
    gaps = [0.25] * (len(lines) - 1) + [0.5]
    total = sum(duration(m) for m in raw) + sum(gaps)
    # إذا أطول من الحد نسرّعه شوية (لحد 20%)
    tempo = min(1.2, max(1.0, total / (MAX_SECONDS - 0.2)))
    wavs, durs = [], []
    for i, mp3 in enumerate(raw):
        wav = workdir / f"line{i}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-af",
                        f"atempo={tempo:.3f},apad=pad_dur={gaps[i]}", "-ar", "44100", "-ac", "2",
                        str(wav)], check=True)
        wavs.append(wav)
        durs.append(duration(wav))
    lst = workdir / "voice_list.txt"
    lst.write_text("".join(f"file '{w.name}'\n" for w in wavs), encoding="utf-8")
    out = workdir / "voice.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(out)], check=True, cwd=workdir)
    log(f"الصوت: {voice} | {sum(durs):.1f} ثانية | سرعة {tempo:.2f}")
    return out, durs


# ------------------------- اللقطات (فيديو + صور) -------------------------
BAD = ("woman", "man", "girl", "boy", "people", "person", "face", "portrait", "selfie")


def relevant(tags, words):
    tags = tags.lower()
    return any(w in tags for w in words) and not any(b in tags for b in BAD)


def pixabay_videos(query, words, used):
    r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
        "key": PIXABAY_API_KEY, "q": query, "per_page": 50, "safesearch": "true"})
    r.raise_for_status()
    return [h for h in r.json().get("hits", [])
            if f"pb{h['id']}" not in used and relevant(h.get("tags", ""), words)
            and h.get("duration", 0) >= 4]


def pixabay_images(query, words, used):
    r = requests.get("https://pixabay.com/api/", timeout=30, params={
        "key": PIXABAY_API_KEY, "q": query, "image_type": "photo", "per_page": 60,
        "safesearch": "true", "order": "popular"})
    r.raise_for_status()
    return [h for h in r.json().get("hits", [])
            if f"img{h['id']}" not in used and relevant(h.get("tags", ""), words)]


def get_media(query, history, workdir, n=3):
    if not PIXABAY_API_KEY:
        raise RuntimeError("PIXABAY_API_KEY مفقود")
    used = set(map(str, history.setdefault("pexels_ids", [])))
    words = [w.lower() for w in query.split() if len(w) > 2] or [query.lower()]
    queries = [query] + [w for w in words if w != query.lower()]
    vids, imgs = [], []
    for q in queries:
        if not vids:
            vids = pixabay_videos(q, words, used)
        if not imgs:
            imgs = pixabay_images(q, words, used)
        if vids and imgs:
            break
    random.shuffle(vids)
    random.shuffle(imgs)
    # نخلط: فيديو، صورة، فيديو (أو الموجود)
    plan = []
    for kind in ("video", "image", "video", "image"):
        src = vids if kind == "video" else imgs
        if src:
            plan.append((kind, src.pop(0)))
        if len(plan) == n:
            break
    while len(plan) < n and (vids or imgs):
        plan.append(("video", vids.pop(0)) if vids else ("image", imgs.pop(0)))
    if not plan:
        raise RuntimeError(f"ما لگينا لقطات لـ {query}")

    media, authors = [], []
    for i, (kind, h) in enumerate(plan):
        if kind == "video":
            files = [f for f in h["videos"].values() if f.get("url")]
            vert = [f for f in files if f["height"] > f["width"]]
            f = max(vert or files, key=lambda f: f["width"] * f["height"]
                    if f["width"] * f["height"] <= 1920 * 1920 else 0)
            p = workdir / f"m{i}.mp4"
            gv.download(f["url"], p)
            history["pexels_ids"].append(f"pb{h['id']}")
        else:
            p = workdir / f"m{i}.jpg"
            gv.download(h["largeImageURL"], p)
            history["pexels_ids"].append(f"img{h['id']}")
        media.append((kind, p))
        authors.append(h["user"])
    log("اللقطات: " + ", ".join(k for k, _ in media))
    while len(media) < n:
        media.append(media[len(media) % len(media)])
    return media, ", ".join(dict.fromkeys(authors))


# ------------------------- التركيب -------------------------
def build(media, voice, durs, overlays, logo, music, out):
    D = sum(durs)
    n = len(media)
    X = 0.4
    L = D / n + X * (n - 1) / n
    frames = int(L * 30) + 1

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for kind, p in media:
        cmd += (["-stream_loop", "-1", "-i", str(p)] if kind == "video" else ["-i", str(p)])
    for ov, _, _ in overlays:
        cmd += ["-i", str(ov)]
    li = n + len(overlays)
    cmd += ["-i", str(logo), "-i", str(voice)]
    vi = li + 1
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]

    look = "eq=brightness=-0.03:contrast=1.06:saturation=1.15"
    parts = []
    for i, (kind, p) in enumerate(media):
        if kind == "video":
            parts.append(
                f"[{i}:v]trim=duration={L:.3f},setpts=PTS-STARTPTS,"
                f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30,"
                f"{look},setsar=1[i{i}]")
        else:
            z = random.choice([f"1+0.14*on/{frames}", f"1.14-0.14*on/{frames}"])
            parts.append(
                f"[{i}:v]scale=1620:2880:force_original_aspect_ratio=increase,crop=1620:2880,"
                f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps=30,"
                f"{look},trim=duration={L:.3f},setpts=PTS-STARTPTS,setsar=1[i{i}]")
    cur = "[i0]"
    for k in range(1, n):
        parts.append(f"{cur}[i{k}]xfade=transition=fade:duration={X}:offset={k * (L - X):.3f}[x{k}]")
        cur = f"[x{k}]"
    for j, (_, a, b) in enumerate(overlays):
        parts.append(f"{cur}[{n + j}:v]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[o{j}]")
        cur = f"[o{j}]"
    parts.append(f"{cur}[{li}:v]overlay=0:0,format=yuv420p[v]")

    fmt = "aformat=sample_rates=44100:channel_layouts=stereo"
    parts.append(f"[{vi}:a]{fmt},volume=1.25[vo]")
    if music:
        parts.append(f"[{vi + 1}:a]{fmt},volume={FACTS_MUSIC_VOLUME},afade=t=out:st={max(0, D - 1):.2f}:d=1[mu]")
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

    script = write_script(history)
    voice_name = pick_voice(history)
    lines = [script["intro_say"]] + [f["say"] for f in script["facts"]]
    voice, durs = tts_lines(lines, voice_name, workdir)

    # كل نص يطلع بنفس وقت جملته بالصوت
    overlays = []
    p = workdir / "ov_intro.png"
    render_intro(script["headline_top"], script["headline_main"], p)
    overlays.append((p, 0, durs[0]))
    t = durs[0]
    for i, f in enumerate(script["facts"]):
        p = workdir / f"ov_fact{i}.png"
        render_fact(f["screen"], p)
        overlays.append((p, t, t + durs[i + 1]))
        t += durs[i + 1]
    logo = workdir / "logo.png"
    render_logo(logo)

    media, author = get_media(script["pixabay_query"], history, workdir, n=3)
    music, music_credit = gv.get_music(history, workdir) if gv.MUSIC_ENABLED else (None, None)
    video = workdir / "video.mp4"
    build(media, voice, durs, overlays, logo, music, video)

    credits = f"\n\nلقطات: {author} (Pixabay)"
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
        "topic": script["topic"],
        "voice": voice_name,
        "created_at": datetime.now().isoformat(),
    }
    (workdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    for f in workdir.iterdir():
        if f.name not in ("video.mp4", "meta.json"):
            f.unlink()

    history["fact_categories"].append(script["category"])
    history["fact_topics"].append(script["topic"])
    history["fact_openings"].append(script["intro_say"])
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
