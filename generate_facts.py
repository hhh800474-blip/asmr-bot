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
MAX_SECONDS = float(os.getenv("MAX_SECONDS", "20"))
LOGO_TEXT = os.getenv("LOGO_TEXT", "#لمحة")
FACTS_MUSIC_VOLUME = float(os.getenv("FACTS_MUSIC_VOLUME", "0.10"))
# الأصوات تتبدل بالترتيب: شاب، بنت، شاب، بنت...
VOICES = [v.strip() for v in os.getenv(
    "FACTS_VOICES", "ar-SA-HamedNeural,ar-SA-ZariyahNeural,ar-AE-HamdanNeural,ar-AE-FatimaNeural"
).split(",") if v.strip()]

# المجالات اللي جابت أعلى مشاهدات بيوتيوب وفيسبوك وتيك توك: تجارب يعيشها الإنسان بجسمه ويومه
WINNING = ["النوم", "جسم الإنسان", "الدماغ والذاكرة", "الأكل والجوع وعادات الطعام", "عادات يومية نفعلها دون أن ننتبه"]

CATEGORIES = WINNING + [
    "صحة وعادات يومية", "رياضة ولياقة", "جسم الإنسان", "علم النفس والسلوك", "النوم",
    "تغذية وفوائد الأكل", "الفضاء والكون", "عالم الحيوان", "الطبيعة والأرض",
    "علوم مدهشة", "الدماغ والذاكرة", "الماء والترطيب",
]
CATEGORIES = list(dict.fromkeys(CATEGORIES))   # بدون تكرار


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
    text = (text.replace("?", "؟").replace(",", "،").replace(";", "؛")
                .replace('"', "").replace("'", "").replace("!", "").replace(":", " "))
    text = text.rstrip(" .…").replace(".", "،")
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
    # الجملة كاملة على الشاشة: نصغّر الخط إذا طويلة حتى ما تتجاوز 3 أسطر
    for size in (74, 66, 58):
        f = font(size)
        lines = wrap(d, text, f, 920)
        if len(lines) <= 3:
            break
    y = 1220 - (len(lines) - 1) * 55
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


TASHKEEL = "".join(chr(c) for c in range(0x064B, 0x0653)) + "\u0670"


def strip_tashkeel(t):
    return "".join(ch for ch in t if ch not in TASHKEEL)


SHADDA = "\u0651"


def soften_endings(t):
    """نشيل حركة آخر الكلمة والتنوين (نقرا بالوقف) حتى ما يطلع النطق متكلف مثل: ذِكْرَىً قَدِيمَةً"""
    out = []
    for w in t.split():
        core = w.rstrip("؟?!.،,:؛")
        tail = w[len(core):]
        chars = list(core)
        while chars and chars[-1] in TASHKEEL and chars[-1] != SHADDA:
            chars.pop()
        out.append("".join(chars) + tail)
    return " ".join(out)


def review_pronunciation(lines):
    """مراجعة ثانية: Gemini يتأكد إن تشكيل كل كلمة يطابق معناها بالجملة"""
    prompt = f"""هذه جمل سيقرأها قارئ صوت آلي بالعربية:
{json.dumps(lines, ensure_ascii=False)}
راجع كل كلمة يمكن أن تُقرأ بأكثر من طريقة، وتأكد أن تشكيلها يطابق المعنى في الجملة.
إذا وجدت كلمة نادرة أو صعبة النطق، استبدلها بكلمة شائعة بنفس المعنى.
لا تغيّر معنى الجمل ولا تضف كلمات. لا تضع حركات الإعراب ولا التنوين على آخر الكلمات.
أرجع JSON فقط: {{"lines": [نفس عدد الجمل بنفس الترتيب]}}"""
    res = gv.gemini_json(prompt)
    fixed = (res or {}).get("lines") if isinstance(res, dict) else None
    if isinstance(fixed, list) and len(fixed) == len(lines) and all(isinstance(x, str) and x.strip() for x in fixed):
        for a, b in zip(lines, fixed):
            if strip_tashkeel(a) != strip_tashkeel(b):
                log(f"تصحيح نطق: {strip_tashkeel(a)} ← {strip_tashkeel(b)}")
        return fixed
    return lines


# ------------------------- السكربت -------------------------
def write_script(history):
    cats = history.setdefault("fact_categories", [])
    # 70% من المجالات الناجحة (حسب أرقام القنوات)، و30% تجارب من الباقي
    pool = WINNING if random.random() < 0.7 else [c for c in CATEGORIES if c not in WINNING]
    fresh = [c for c in pool if c not in cats[-2:]] or pool
    cat = random.choice(fresh)
    topics = history.setdefault("fact_topics", [])[-60:]
    openings = history.setdefault("fact_openings", [])[-12:]
    prompt = f"""أنت كاتب لقناة "لمحة" التي تنشر معلومة سريعة بالعربي في فيديو قصير (من 10 إلى 20 ثانية حسب الحاجة).
المجال هذه المرة: {cat}
اختر موضوعاً محدداً جديداً داخل هذا المجال، مختلفاً عن هذه المواضيع السابقة: {topics}

قواعد الدقة (مهمة جداً):
- معلومات صحيحة ومعروفة علمياً فقط. إذا لم تكن متأكداً فاختر موضوعاً آخر.
- ممنوع ادعاء أن شيئاً يعالج أو يشفي أو يمنع مرضاً. استخدم: يساعد، يدعم، قد، يرتبط بـ.
- لا أرقام مبالغ فيها.

قواعد الوضوح (أهم شي):
- الفيديو لازم يكون مفهوم لأي شخص عادي من أول مرة، بدون مصطلحات علمية صعبة.
- فكرة واحدة فقط، مكتملة: سؤال/بداية ← الجواب المباشر ← سبب أو توضيح بسيط.
- الجملة الثانية لازم تجاوب على البداية بشكل صريح وواضح. لا ألغاز ولا معلومة ناقصة.
- كل جملة لازم تكون مفهومة لو انقرت لوحدها.
- الأفضل قصير ومباشر: 18-28 كلمة بجملتين. الإيقاع سريع وحيوي.
  فقط إذا الموضوع ما ينفهم بدون توضيح إضافي، استخدم 3 جمل (لحد 36 كلمة).

قواعد الأسلوب:
- البداية مختلفة عن هذه البدايات السابقة: {openings}
- لا تبدأ بـ "هل تعلم".
- أول جملة هي أهم شي بالفيديو: 75% من الناس يقررون يكملون أو يمررون بأول ثانيتين.
  اجعلها تخاطب المشاهد مباشرة بتجربة عاشها بنفسه أو شي يخصه، مثل:
  "هل شعرت يوماً أنك تسقط وأنت نائم؟"، "لماذا تتثاءب عندما ترى غيرك يتثاءب؟"،
  "توقف عن شرب الماء بهذه الطريقة"، "جسمك يفعل هذا كل ليلة دون أن تشعر".
  ممنوع البدايات العامة الباردة مثل "معلومة عن..." أو "اكتشف العلماء...".
- عربية فصحى سهلة جداً، كلمات يومية. لا تطلب المتابعة ولا الاشتراك.

مثال جيد:
intro_say: "لماذا نشعر بالنعاس بعد الأكل؟"
facts: ["لأن الجسم يرسل دماً أكثر إلى المعدة لهضم الطعام", "فيقل نشاطك قليلاً، خصوصاً بعد وجبة كبيرة"]

أرجع JSON فقط:
- topic: الموضوع بكلمتين
- headline_top: سطر علوي قصير (2-4 كلمات) يشد ويخاطب المشاهد، مثل "حصلت لك؟" أو "جسمك يفعلها" أو "لا تتجاهلها"
- headline_main: الكلمة الأساسية للموضوع (1-3 كلمات)
- intro_say: جملة البداية المنطوقة (4-8 كلمات) بدون تشكيل
- intro_voiced: نفس جملة البداية بالضبط، مع تشكيل الكلمات المحتملة للبس فقط (للقارئ الآلي)
- facts: قائمة من 2 أو 3 عناصر، الأول هو الجواب والباقي توضيح، كل عنصر فيه:
    say: الجملة (7-13 كلمة) بدون تشكيل، للشاشة
    voiced: نفس الجملة بالضبط، مع تشكيل الكلمات المحتملة للبس فقط
  قواعد النطق (مهمة جداً لأن قارئاً آلياً سيقرأ الكلام):
  - استخدم كلمات شائعة يقولها الناس يومياً. تجنب الكلمات النادرة والمثنى المضاف الصعب.
    مثال: "نصفي الدماغ" أو "جزأين من الدماغ" بدل "فصي دماغك".
  - شكّل الكلمة التي تُقرأ بأكثر من طريقة حسب معناها، مثل: مُرَكَّبات (مواد) وليس مَرْكَبات (سيارات)،
    فَيُسَجِّل، عِلْم/عَلَم، يُحَسِّن/يَحْسُن.
  - لا تضع حركات الإعراب ولا التنوين على آخر الكلمات، حتى يكون النطق طبيعياً وليس متكلفاً.
- clarity_score: من 1 إلى 10، كم يفهمها شخص عادي من أول مرة (كن صارماً)
- pixabay_queries: قائمة من 3 عبارات بحث إنجليزية (2-3 كلمات) لتصوير فيديو حقيقي يوضح المعلومة بالضبط.
  الأولى أقوى لقطة افتتاحية تشد النظر وتطابق السؤال حرفياً (مثال: معلومة عن الرمش = "eye blinking", "eye close up", "eyes").
  أشياء حقيقية تُصوَّر بالكاميرا فقط، لا رسوم ولا خيال علمي.
- title: عنوان على شكل سؤال يثير الفضول، أقل من 60 حرف، مع إيموجي واحد
- description: جملة واحدة
- hashtags: 4 هاشتاغات عربية"""
    res = None
    for attempt in range(3):
        cand = gv.gemini_json(prompt)
        if not cand or not cand.get("facts") or not cand.get("intro_say"):
            continue
        facts = []
        for f in cand["facts"][:3]:
            say = f.get("say") if isinstance(f, dict) else str(f)
            voiced = (f.get("voiced") if isinstance(f, dict) else None) or say
            if say:
                say = strip_tashkeel(say)
                # الشاشة = نفس الكلام (بدون تشكيل)، والصوت يقرا النسخة المشكّلة حتى ينطق صح
                facts.append({"say": say, "screen": say, "voiced": voiced})
        cand["facts"] = facts
        words = len(cand["intro_say"].split()) + sum(len(f["say"].split()) for f in facts)
        score = float(cand.get("clarity_score", 0) or 0)
        log(f"محاولة {attempt + 1}: كلمات={words} وضوح={score}")
        if len(facts) >= 2 and words <= 38 and score >= 8:
            res = cand
            break
        res = res or (cand if len(facts) >= 2 else None)
    if not res:
        raise RuntimeError("Gemini ما رجّع سكربت")
    res["facts"] = [f for f in res["facts"] if f.get("say") and f.get("screen")][:3]
    if not res["facts"]:
        raise RuntimeError("السكربت ناقص")
    res["intro_say"] = strip_tashkeel(res["intro_say"])
    res.setdefault("topic", cat)
    res.setdefault("headline_top", "معلومة سريعة")
    res.setdefault("headline_main", res["topic"])
    qs = res.get("pixabay_queries") or [res.get("pixabay_query") or "nature"]
    res["pixabay_queries"] = [q for q in qs if isinstance(q, str) and q.strip()][:3] or ["nature"]
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
        asyncio.run(edge_tts.Communicate(text, voice, rate="+12%").save(str(mp3)))
        raw.append(mp3)
    gaps = [0.12] * (len(lines) - 1) + [0.3]
    total = sum(duration(m) for m in raw) + sum(gaps)
    # إذا أطول من الحد نسرّعه شوية (لحد 20%)
    tempo = min(1.15, max(1.0, total / (MAX_SECONDS - 0.2)))
    wavs, durs = [], []
    for i, mp3 in enumerate(raw):
        wav = workdir / f"line{i}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-af",
                        f"silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.02,"
                        f"areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
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
# أي شي مو تصوير حقيقي نرفضه: رسوم، 3D، خيال علمي، فن رقمي...
ART = {"3d", "render", "rendering", "illustration", "cartoon", "anime", "drawing", "fantasy",
       "digital", "surreal", "sci-fi", "scifi", "ufo", "alien", "aliens", "artificial",
       "ai", "generated", "manipulation", "painting", "art", "artwork", "graphic", "vector",
       "animation", "animated", "cgi", "futuristic", "mystical", "magic", "dream", "abstract",
       "background", "wallpaper", "pattern", "texture", "model", "avatar", "character"}
# محتوى غير لائق: نرفضه دائماً حتى لو الموضوع عن الجلد أو الجسم
NSFW = {"erotic", "eroticism", "erotica", "sexy", "sex", "sensual", "seductive", "seduction",
        "nude", "naked", "nudity", "topless", "bikini", "lingerie", "underwear", "bra",
        "swimsuit", "swimwear", "lust", "intimate", "intimacy", "boudoir", "hot", "kiss",
        "kissing", "bed", "bedroom", "couple", "lovers", "romance", "romantic", "act", "partial"}
STOP = {"the", "and", "with", "close", "closeup", "up", "of", "in", "on", "a", "an", "slow", "motion"}


def tag_words(tags):
    return {w for t in tags.lower().split(",") for w in t.strip().split()}


def score(h, words):
    """كم كلمة من البحث موجودة بالوسوم. الصفر يعني مو مناسب، و-1 يعني رسوم/مو حقيقي"""
    tw = tag_words(h.get("tags", ""))
    if tw & ART or tw & NSFW:
        return -1
    return len(set(words) & tw)


def pixabay_videos(query, used):
    r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
        "key": PIXABAY_API_KEY, "q": query, "per_page": 60, "safesearch": "true",
        "video_type": "film"})            # film = تصوير حقيقي فقط (مو أنيميشن)
    r.raise_for_status()
    return [h for h in r.json().get("hits", [])
            if f"pb{h['id']}" not in used and h.get("duration", 0) >= 4]


def pixabay_images(query, used):
    r = requests.get("https://pixabay.com/api/", timeout=30, params={
        "key": PIXABAY_API_KEY, "q": query, "image_type": "photo", "per_page": 80,
        "safesearch": "true"})
    r.raise_for_status()
    return [h for h in r.json().get("hits", []) if f"img{h['id']}" not in used]


def best(hits, words, k):
    """نرتب حسب التطابق ونختار من الأفضل (مع شوية تنويع)"""
    scored = [(score(h, words), random.random(), h) for h in hits]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[0][0] if scored else 0
    good = [x[2] for x in scored if x[0] >= top][:max(k * 3, 6)]
    random.shuffle(good)
    if len(good) < k:                       # إذا قليلة نكمل بالأقل تطابق (بس مو صفر)
        good += [x[2] for x in scored if 0 < x[0] < top][:k * 2]
    return good


def download_retry(url, path, tries=4):
    """Pixabay أحياناً يرجع 429 (طلبات كثيرة). ننتظر ونعيد بدل ما يفشل الفيديو كله"""
    import time
    for k in range(tries):
        try:
            return gv.download(url, path)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if code in (429, 500, 502, 503) and k < tries - 1:
                wait = 5 * (2 ** k)
                log(f"Pixabay رد {code}، ننتظر {wait} ثانية ونعيد")
                time.sleep(wait)
                continue
            raise
        except requests.RequestException:
            if k < tries - 1:
                time.sleep(5)
                continue
            raise


def get_media(queries, history, workdir, n=3):
    if not PIXABAY_API_KEY:
        raise RuntimeError("PIXABAY_API_KEY مفقود")
    if isinstance(queries, str):
        queries = [queries]
    used = set(map(str, history.setdefault("pexels_ids", [])))
    vids, imgs, seen = [], [], set()
    for q in queries:
        words = [w.lower() for w in q.split() if len(w) > 2 and w.lower() not in STOP] or [q.lower()]
        for h in best(pixabay_videos(q, used), words, n):
            if ("v", h["id"]) not in seen:
                seen.add(("v", h["id"])); vids.append(h)
        for h in best(pixabay_images(q, used), words, n):
            if ("i", h["id"]) not in seen:
                seen.add(("i", h["id"])); imgs.append(h)
        if len(vids) >= 2 and len(imgs) >= 2:
            break
    log(f"لقيت: {len(vids)} فيديو حقيقي، {len(imgs)} صورة")
    # البداية لازم تكون فيديو حقيقي متحرك حتى تشد النظر، وبعدها نخلط
    order = ("video", "image", "video", "video") if len(vids) >= 3 else ("video", "image", "video", "image")
    order = list(order[:n]) + ["video", "image"] * n      # احتياط إذا فشل تحميل لقطة

    media, authors = [], []
    for kind in order:
        if len(media) == n:
            break
        src = vids if kind == "video" else imgs
        if not src:
            src = imgs if kind == "video" else vids
            kind = "image" if kind == "video" else "video"
        if not src:
            break
        h = src.pop(0)
        i = len(media)
        try:
            if kind == "video":
                files = [f for f in h["videos"].values() if f.get("url")]
                vert = [f for f in files if f["height"] > f["width"]]
                f = max(vert or files, key=lambda f: f["width"] * f["height"]
                        if f["width"] * f["height"] <= 1920 * 1920 else 0)
                p = workdir / f"m{i}.mp4"
                download_retry(f["url"], p)
                history["pexels_ids"].append(f"pb{h['id']}")
            else:
                p = workdir / f"m{i}.jpg"
                url = h.get("largeImageURL") or h.get("webformatURL")
                try:
                    download_retry(url, p)
                except Exception:
                    download_retry(h["webformatURL"], p)      # نسخة أصغر إذا الكبيرة رفضت
                history["pexels_ids"].append(f"img{h['id']}")
        except Exception as e:
            log(f"تخطينا لقطة ما تحملت ({str(e)[:80]})")
            continue
        media.append((kind, p))
        authors.append(h["user"])
        log(f"لقطة {i + 1} ({kind}): {h.get('tags')}")
    if not media:
        raise RuntimeError(f"ما گدرنا نحمّل أي لقطة لـ {queries}")
    while len(media) < n:
        media.append(media[len(media) % len(media)])
    return media, ", ".join(dict.fromkeys(authors))


# ------------------------- التركيب -------------------------
def visible_start(path):
    """كثير من لقطات Pixabay تبدي بشاشة سودة أو تظهر تدريجياً (fade in).
    نقيس إضاءة أول 4 ثواني ونبدي من أول لحظة توصل لإضاءتها الطبيعية"""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-t", "4", "-i", str(path), "-an", "-vf",
                              "fps=10,signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                              "-f", "null", "-"], capture_output=True, text=True).stderr
        vals = [float(l.split("=")[-1]) for l in out.splitlines() if "YAVG=" in l]
        if not vals:
            return 0.3
        normal = sorted(vals)[len(vals) // 2]          # الإضاءة الطبيعية للقطة
        for k, v in enumerate(vals):
            if v >= max(18, 0.8 * normal):
                return round(max(0.3, k / 10 + 0.1), 2)
        return 0.3
    except Exception:
        return 0.5


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
            # أول لقطة: زوم سريع لداخل بأول ثانية حتى تشد العين
            punch = (f",zoompan=z='if(lt(on,30),1.18-0.18*on/30,1)':x='iw/2-(iw/zoom/2)'"
                     f":y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps=30") if i == 0 else ""
            st = visible_start(p)
            parts.append(
                f"[{i}:v]trim=start={st:.2f}:duration={L:.3f},setpts=PTS-STARTPTS,"
                f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30"
                f"{punch},{look},setsar=1[i{i}]")
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
        parts.append("[vo][mu]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        parts.append("[vo]loudnorm=I=-14:TP=-1.5:LRA=11[a]")

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
    lines = ([script.get("intro_voiced") or script["intro_say"]]
             + [f.get("voiced") or f["say"] for f in script["facts"]])
    lines = review_pronunciation(lines)
    lines = [soften_endings(l) for l in lines]
    # إذا المراجعة بدّلت كلمة صعبة، نخلي نص الشاشة نفس الكلام المنطوق
    script["intro_say"] = strip_tashkeel(lines[0])
    for f, l in zip(script["facts"], lines[1:]):
        f["say"] = f["screen"] = strip_tashkeel(l)
    log("النص المنطوق: " + " | ".join(lines))
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

    n_shots = 3 if sum(durs) <= 15 else 4      # الفيديو الأطول ياخذ لقطة زيادة حتى ما يمل
    media, author = get_media(script["pixabay_queries"], history, workdir, n=n_shots)
    try:
        music, music_credit = gv.get_music(history, workdir) if gv.MUSIC_ENABLED else (None, None)
    except Exception as e:
        log(f"نكمل بدون موسيقى ({str(e)[:60]})")      # الموسيقى إضافة، ما نوگف الفيديو بسببها
        music, music_credit = None, None
    video = workdir / "video.mp4"
    build(media, voice, durs, overlays, logo, music, video)

    credits = f"\n\nلقطات: {author} (Pixabay)"
    if music_credit:
        credits += f"\nموسيقى: {music_credit['author']} (Freesound)"
    credits += "\nالصوت مولّد بالذكاء الاصطناعي. معلومات عامة وليست نصيحة طبية."
    meta = {
        "title": script["title"][:100],
        "description": (script["description"] + "\n\n👇 ما المعلومة التي تريد أن نشرحها في الفيديو القادم؟\n\n"
                        + " ".join(script["hashtags"]) + credits),
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
