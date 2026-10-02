"""
مولّد فيديوهات ASMR قصيرة (15 ثانية) تلقائي
--------------------------------
1) Gemini يختار فكرة + عنوان + وصف + همسات
2) Pixabay (أو Pexels) يجيب فيديو مطابق للفكرة
3) Freesound يجيب أصوات (رخصة CC0 فقط)
4) Edge-TTS يولّد صوت همس ناعم
5) FFmpeg يركّب فيديو 1080x1920 مع نص تشويقي بأول 3 ثواني

التشغيل:  python generate_video.py
الناتج:   output/<التاريخ>/video.mp4  +  meta.json
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

# ------------------------- الإعدادات -------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()  # strip يشيل المسافات والأسطر الزايدة
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip()
# نجرب الموديلات بالترتيب، إذا واحد انلغى ينتقل للي بعده
GEMINI_MODELS = [m for m in [GEMINI_MODEL, "gemini-flash-latest", "gemini-3-flash-preview",
                              "gemini-2.5-flash", "gemini-flash-lite-latest"] if m]
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()  # strip يشيل المسافات والأسطر الزايدة
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()  # strip يشيل المسافات والأسطر الزايدة
FREESOUND_API_KEY = os.getenv("FREESOUND_API_KEY", "").strip()  # strip يشيل المسافات والأسطر الزايدة

VIDEO_SECONDS = float(os.getenv("VIDEO_SECONDS", "15"))        # أطول مدة
VIDEO_MIN_SECONDS = float(os.getenv("VIDEO_MIN_SECONDS", "7"))  # أقصر مدة
HOOK_TEXT_ENABLED = os.getenv("HOOK_TEXT_ENABLED", "1") == "1"
CONTENT_LANG = os.getenv("CONTENT_LANG", "en")             # en أو ar
VOICE = os.getenv("VOICE", "en-US-AriaNeural")             # للعربي: ar-SA-ZariyahNeural
VOICE_ENABLED = os.getenv("VOICE_ENABLED", "0") == "1"      # الافتراضي: بدون كلام
MUSIC_ENABLED = os.getenv("MUSIC_ENABLED", "1") == "1"      # موسيقى هادئة خفيفة بالخلفية
MUSIC_VOLUME = float(os.getenv("MUSIC_VOLUME", "0.38" if os.getenv("STYLE", "energetic") == "energetic" else "0.18"))
CLIPS_ARE_AI = os.getenv("CLIPS_ARE_AI", "1") == "1"
STYLE = os.getenv("STYLE", "energetic").strip().lower()      # energetic = حماس | calm = هادئ
MONTAGE_CLIPS = int(os.getenv("MONTAGE_CLIPS", "3" if STYLE == "energetic" else "1"))   # فيديوهات clips مولدة بالذكاء؟ (للإفصاح بالمنصات)

BASE = Path(__file__).parent
OUT_ROOT = BASE / "output"
CLIPS_DIR = BASE / "clips"   # حط فيديوهاتك هنا (مصورة أو مولدة بالذكاء) وتنستخدم قبل Pixabay
HISTORY_FILE = BASE / "history.json"

# قائمة البحث المسموحة: لقطات satisfying فقط (Gemini يختار منها)
# كل عنصر: كلمة البحث، الكلمات اللي لازم تكون بوسوم الفيديو، أصوات مناسبة
SATISFYING = {
    "slime":            (["slime"], ["slime squish", "slime"]),
    "kinetic sand":     (["sand", "kinetic"], ["sand crunch", "sand"]),
    "paint mixing":     (["paint", "mixing"], ["paint mixing", "squish"]),
    "paint pouring":    (["paint", "pour", "acrylic"], ["pouring liquid", "paint"]),
    "fluid art":        (["fluid", "paint", "acrylic", "art"], ["liquid flow", "pouring"]),
    "ink in water":     (["ink", "water"], ["underwater", "water bubbles"]),
    "honey pouring":    (["honey", "pour", "syrup"], ["sticky liquid pour", "honey"]),
    "chocolate pouring": (["chocolate"], ["pouring liquid", "chocolate"]),
    "melting chocolate": (["chocolate", "melt"], ["sizzle", "liquid"]),
    "soap cutting":     (["soap"], ["soap cutting", "knife cutting"]),
    "cutting cake":     (["cake", "cutting", "knife"], ["knife cutting", "cake"]),
    "ice cubes":        (["ice"], ["ice crunch", "ice cubes glass"]),
    "pouring water":    (["water", "pour", "glass"], ["pouring water glass", "water"]),
    "foam":             (["foam", "bubbles"], ["foam", "fizz"]),
    "bubbles macro":    (["bubble", "bubbles"], ["fizz", "bubbles"]),
    "glitter":          (["glitter"], ["glitter", "shaker"]),
    "pottery wheel":    (["pottery", "clay"], ["clay", "pottery"]),
    "dough kneading":   (["dough", "kneading"], ["dough", "squish"]),
    "cream whipping":   (["cream", "whip"], ["whisk", "mixing bowl"]),
    "candle wax":       (["wax", "candle"], ["candle", "match strike"]),
}
# وسوم نرفضها حتى ما تطلع حشرات وورود ومناظر طبيعية
BANNED_TAGS = {"bee", "insect", "flower", "flowers", "animal", "bird", "dog", "cat",
               "landscape", "mountain", "sky", "sea", "beach", "city", "woman", "man",
               "people", "person", "girl", "boy", "face", "portrait", "tree", "forest"}

# قائمة الحماس: حركة قوية وانفجارات ورذاذ بالتصوير البطيء
ENERGETIC = {
    "paint explosion":    (["paint", "explosion", "color"], ["explosion", "splash"]),
    "powder explosion":   (["powder", "explosion", "holi", "dust"], ["explosion", "impact"]),
    "slow motion splash": (["splash", "liquid", "water"], ["water splash", "splash"]),
    "milk splash":        (["milk", "splash"], ["liquid splash", "splash"]),
    "fruit splash":       (["fruit", "splash"], ["water splash", "splash"]),
    "sparks":             (["spark", "sparks", "welding", "grinder"], ["metal grinding", "sparks"]),
    "molten metal":       (["molten", "metal", "foundry", "steel"], ["fire roar", "sizzle"]),
    "lava":               (["lava", "magma", "volcano"], ["fire roar", "lava"]),
    "fire":               (["fire", "flame", "flames"], ["fire roar", "fire crackling"]),
    "fireworks":          (["fireworks", "firework"], ["fireworks", "explosion"]),
    "lightning":          (["lightning", "thunder", "storm"], ["thunder", "thunderstorm"]),
    "glass breaking":     (["glass", "break", "shatter", "broken"], ["glass shatter", "glass breaking"]),
    "balloon pop":        (["balloon", "pop"], ["balloon pop", "pop"]),
    "colored smoke":      (["smoke"], ["whoosh", "wind"]),
    "liquid gold":        (["gold", "golden", "liquid"], ["liquid flow", "pouring"]),
    "paint pouring":      (["paint", "pour", "acrylic"], ["pouring liquid", "paint"]),
    "fluid art":          (["fluid", "paint", "acrylic"], ["liquid flow", "pouring"]),
    "ink in water":       (["ink", "water"], ["underwater", "bubbles"]),
}
if STYLE == "energetic":
    SATISFYING = ENERGETIC
    BANNED_TAGS = BANNED_TAGS - {"sky", "sea", "beach", "city", "mountain", "landscape"}

# أفكار احتياطية إذا Gemini ما اشتغل
HOOKS = ["Wait for the last one...", "Watch till the end", "The ending is so satisfying",
         "Only 1% hear the last sound", "Headphones on... trust me", "You'll watch this twice",
         "Wait for it...", "This sound is unreal"]
PRESETS = [{"theme": q, "pexels_query": q, "sounds": v[1], "hook": random.choice(HOOKS)}
           for q, v in SATISFYING.items()]


# ------------------------- أدوات مساعدة -------------------------
def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def load_history():
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"titles": [], "pexels_ids": [], "freesound_ids": []}


def save_history(h):
    for k in h:
        h[k] = h[k][-200:]  # نحتفظ بآخر 200 فقط
    HISTORY_FILE.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")


def download(url, path, headers=None):
    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    return path


# ------------------------- 1) الفكرة -------------------------
def get_idea(history, forced_theme=None):
    preset = random.choice(PRESETS)
    if forced_theme:
        preset = {"theme": forced_theme, "pexels_query": forced_theme,
                  "sounds": ["crunch", "squish"], "hook": random.choice(HOOKS)}
    fallback = {
        **preset,
        "hook": preset.get("hook", "Wait for it..."),
        "title": f"{preset['theme'].capitalize()} ASMR 🤫 wait for the end",
        "description": f"Satisfying {preset['theme']} sounds. Headphones on.",
        "hashtags": ["#asmr", "#satisfying", "#oddlysatisfying", "#relaxing", "#shorts"],
        "whisper": "Shh... listen... this part is my favorite...",
    }
    if not GEMINI_API_KEY:
        log("ما كو مفتاح Gemini، نستخدم فكرة جاهزة")
        return fallback

    lang_note = "Arabic" if CONTENT_LANG == "ar" else "English"
    forced = (f"IMPORTANT: the video is already filmed and shows: '{forced_theme}'. "
              f"Write theme, sounds, hook and title to match it exactly.\n") if forced_theme else ""
    recent = history["titles"][-20:]
    STYLE_NOTE = ("Make it HIGH ENERGY: explosions, splashes, sparks, fire, slow-motion impact."
                  if STYLE == "energetic" else
                  "Focus on crisp oddly satisfying close-up actions: cutting, crunching, pouring.")
    prompt = f"""You create ideas for faceless ASMR short videos, max 15 seconds,
designed so viewers watch until the very end and replay.
{STYLE_NOTE}
Avoid repeating these recent titles: {recent}
{forced}Return ONLY JSON with these keys:
- theme: short scene in English
- pexels_query: pick EXACTLY one from this list: {list(SATISFYING)}
- sounds: list of 2 SIMPLE sound search terms, 1-2 common English words each (e.g. "crunch", "pouring water")
- hook: on-screen text for the first 3 seconds, in English, max 6 words,
  creates curiosity, no emoji
- title: curiosity title in {lang_note}, max 60 chars, 1 emoji
- description: 1 short sentence in {lang_note}
- hashtags: 5 hashtags including #asmr and #satisfying
- whisper: ONE whispered line in {lang_note}, 6-10 words, builds anticipation,
  use "..." for pauses"""

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0},
    }
    for model in GEMINI_MODELS:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            r = requests.post(url, json=body, timeout=90,
                              headers={"x-goog-api-key": GEMINI_API_KEY})
            if r.status_code == 404:
                log(f"الموديل {model} غير متوفر، نجرب اللي بعده")
                continue
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            idea = json.loads(text.replace("```json", "").replace("```", "").strip())
            for key in fallback:
                idea.setdefault(key, fallback[key])
            q = str(idea.get("pexels_query", "")).lower().strip()
            if forced_theme:
                q = forced_theme
            elif q not in SATISFYING:
                q = random.choice(list(SATISFYING))
                log(f"Gemini اختار بحث مو بالقائمة، بدلناه بـ: {q}")
            idea["pexels_query"] = q
            log(f"الفكرة ({model}): {idea['title']}")
            return idea
        except Exception as e:
            log(f"Gemini {model} فشل ({str(e)[:150]})")
    log("نستخدم فكرة جاهزة")
    return fallback


# ------------------------- 1.5) النص التشويقي بعد ما نعرف الفيديو -------------------------
HOOK_TEMPLATES = [
    "Rate this {t} from 1 to 10", "POV: the most satisfying {t}", "Can you hear the {t}?",
    "Sound on for this {t}", "Watch the very last second", "I could watch this forever",
    "This {t} hits different", "Tell me this isn't satisfying", "Real or fake? Comment below",
    "Your brain will thank you", "Instant calm in {n} seconds", "Don't skip the ending",
    "Why is this so relaxing?", "Pure {t} therapy", "Headphones on, trust me",
    "This is your sign to relax", "Only 1% watch till the end", "Replay it, I dare you",
]


def norm(h):
    return " ".join("".join(c for c in h.lower() if c.isalnum() or c == " ").split())


def is_repeat(hook, recent):
    n = norm(hook)
    first3 = " ".join(n.split()[:3])
    for r in recent[-15:]:
        rn = norm(r)
        if n == rn or (first3 and first3 == " ".join(rn.split()[:3])):
            return True
    return False


def template_hook(thing, seconds, recent):
    pool = HOOK_TEMPLATES[:]
    random.shuffle(pool)
    for t in pool:
        h = t.format(t=thing, n=int(seconds))
        if not is_repeat(h, recent):
            return h
    return pool[0].format(t=thing, n=int(seconds))


def gemini_json(prompt):
    if not GEMINI_API_KEY:
        return None
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 1.2}}
    for model in GEMINI_MODELS:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                json=body, timeout=90, headers={"x-goog-api-key": GEMINI_API_KEY})
            if r.status_code in (404, 429, 500, 503):
                continue
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text.replace("```json", "").replace("```", "").strip())
        except Exception as e:
            log(f"Gemini {model}: {str(e)[:120]}")
    return None


def write_copy(idea, video_desc, seconds, history):
    """يكتب الهوك والعنوان حسب الفيديو الحقيقي اللي انختار، وبدون تكرار"""
    recent_hooks = history.setdefault("hooks", [])
    thing = (idea.get("pexels_query") or "satisfying").replace(" macro", "").replace(" in water", "")
    lang_note = "Arabic" if CONTENT_LANG == "ar" else "English"
    prompt = f"""You write on-screen text for a {int(seconds)}-second faceless satisfying ASMR short.
What the video ACTUALLY shows: {video_desc}
Write about what is visible. Do NOT mention actions that are not in the video
(e.g. no "slice" or "cut" unless the video shows cutting).
Recent hooks you must NOT repeat or imitate (different wording AND different structure):
{recent_hooks[-15:]}
Pick ONE style at random: question, rating challenge, POV, real-vs-fake, dare, calm statement,
counting, "sound on", emotional reaction. Do not start with "Wait for".
Return ONLY JSON:
- hook: English, max 6 words, no emoji
- title: {lang_note}, max 60 chars, 1 emoji, curiosity
- description: 1 short sentence in {lang_note}
- hashtags: 5 hashtags including #asmr and #satisfying"""
    for _ in range(2):
        res = gemini_json(prompt)
        if res and res.get("hook") and not is_repeat(res["hook"], recent_hooks):
            for k in ("title", "description", "hashtags"):
                if res.get(k):
                    idea[k] = res[k]
            idea["hook"] = res["hook"]
            break
    else:
        idea["hook"] = template_hook(thing, seconds, recent_hooks)
        log("استخدمنا هوك من القوالب")
    if is_repeat(idea["hook"], recent_hooks):
        idea["hook"] = template_hook(thing, seconds, recent_hooks)
    recent_hooks.append(idea["hook"])
    log(f"الهوك: {idea['hook']}")
    return idea


# ------------------------- 2) الفيديو -------------------------
def get_pexels_video(query, history, workdir):
    if not PEXELS_API_KEY:
        raise RuntimeError("PEXELS_API_KEY مفقود")
    headers = {"Authorization": PEXELS_API_KEY}
    r = requests.get("https://api.pexels.com/videos/search", headers=headers, timeout=30,
                     params={"query": query, "orientation": "portrait", "per_page": 30})
    r.raise_for_status()
    videos = [v for v in r.json().get("videos", [])
              if v["id"] not in history["pexels_ids"] and v.get("duration", 0) >= 5]
    if not videos:
        raise RuntimeError(f"ما لقينا فيديو لـ: {query}")
    video = random.choice(videos[:10])

    # نختار أقرب ملف لدقة 1080 عمودي
    files = [f for f in video["video_files"]
             if f.get("width") and f.get("height") and f["height"] > f["width"]]
    files = files or video["video_files"]
    best = min(files, key=lambda f: abs((f.get("width") or 0) - 1080))

    path = workdir / "clip.mp4"
    download(best["link"], path)
    history["pexels_ids"].append(video["id"])
    log(f"فيديو Pexels #{video['id']} من {video['user']['name']}")
    return path, {"pexels_id": video["id"], "author": video["user"]["name"],
                  "url": video["url"]}


def search_pixabay(query, history):
    """يرجع الفيديوهات المناسبة فقط: وسومها تطابق البحث وما بيها حشرات/ناس/طبيعة"""
    r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
        "key": PIXABAY_API_KEY, "q": query, "per_page": 100,
        "safesearch": "true", "order": "popular"})
    r.raise_for_status()
    must = SATISFYING.get(query, ([w for w in query.split()], []))[0]
    good = []
    for h in r.json().get("hits", []):
        tags = {t.strip().lower() for t in h.get("tags", "").split(",")}
        words = set(" ".join(tags).split())
        if f"pb{h['id']}" in history["pexels_ids"] or h.get("duration", 0) < 5:
            continue
        if words & BANNED_TAGS:
            continue
        if not any(m in words or m in " ".join(tags) for m in must):
            continue
        good.append(h)
    return good


def get_pixabay_video(query, history, workdir):
    if not PIXABAY_API_KEY:
        raise RuntimeError("PIXABAY_API_KEY مفقود")
    # نجرب البحث المطلوب، وإذا ما لگينا شي مناسب نجرب غيره من القائمة
    others = [q for q in SATISFYING if q != query]
    random.shuffle(others)
    for q in [query] + others[:6]:
        hits = search_pixabay(q, history)
        log(f"بحث '{q}': {len(hits)} فيديو مناسب")
        if hits:
            break
    else:
        raise RuntimeError("ما لقينا فيديو satisfying مناسب")

    def pick_file(h):
        files = [f for f in h["videos"].values() if f.get("url")]
        vertical = [f for f in files if f["height"] > f["width"]]
        pool = vertical or files
        return max(pool, key=lambda f: f["width"] * f["height"]), bool(vertical)

    scored = [(h, *pick_file(h)) for h in hits]
    vertical = [x for x in scored if x[2]]
    pool = (vertical or scored)[:15]
    if len(pool) < MONTAGE_CLIPS:
        pool = scored[:15]
    random.shuffle(pool)
    chosen = pool[:max(1, MONTAGE_CLIPS)]

    paths, authors, tags = [], [], []
    for i, (h, f, _) in enumerate(chosen):
        p = workdir / f"clip{i}.mp4"
        download(f["url"], p)
        paths.append(p)
        authors.append(h["user"])
        tags.append(h.get("tags", ""))
        history["pexels_ids"].append(f"pb{h['id']}")
        log(f"فيديو Pixabay #{h['id']} | وسوم: {h.get('tags')}")
    return paths, {"author": ", ".join(dict.fromkeys(authors)), "source": "Pixabay",
                   "query": q, "tags": "; ".join(tags)}


def get_video(query, history, workdir):
    if PIXABAY_API_KEY:
        return get_pixabay_video(query, history, workdir)
    path, credit = get_pexels_video(query, history, workdir)
    credit["source"] = "Pexels"
    return [path], credit


# ------------------------- 3) الأصوات -------------------------
GENERIC_SOUNDS = ["crunch", "liquid pour", "squish", "tapping", "water", "rain", "foley"]


def freesound_search(q, history, min_dur):
    r = requests.get("https://freesound.org/apiv2/search/text/", timeout=30, params={
        "query": q,
        "filter": f'license:"Creative Commons 0" duration:[{min_dur} TO 600]',
        "fields": "id,name,username,previews,duration",
        "page_size": 20,
        "token": FREESOUND_API_KEY,
    })
    r.raise_for_status()
    res = r.json().get("results", [])
    fresh = [x for x in res if x["id"] not in history["freesound_ids"]]
    return fresh or res


def candidate_terms(q, video_query):
    """من البحث الدقيق للأعم: الجملة كاملة، كل كلمة لوحدها، أصوات القائمة، أصوات عامة"""
    terms = [q] + [w for w in q.split() if len(w) > 3]
    if video_query in SATISFYING:
        terms += SATISFYING[video_query][1]
    terms += GENERIC_SOUNDS
    seen, out = set(), []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def get_freesound(queries, history, workdir, video_query=""):
    if not FREESOUND_API_KEY:
        raise RuntimeError("FREESOUND_API_KEY مفقود")
    paths, credits, used = [], [], set()
    for i, q in enumerate(queries[:2]):
        found = None
        for term in candidate_terms(q, video_query):
            for min_dur in (10, 2):          # أول شي أصوات طويلة، بعدين نقبل القصيرة (تنعاد تلقائياً)
                try:
                    res = [x for x in freesound_search(term, history, min_dur) if x["id"] not in used]
                except Exception as e:
                    log(f"خطأ ببحث الصوت '{term}': {e}")
                    res = []
                if res:
                    found = random.choice(res[:8])
                    break
            if found:
                if term != q:
                    log(f"ما لقينا '{q}'، استخدمنا '{term}'")
                break
        if not found:
            log(f"ما لقينا صوت لـ: {q}")
            continue
        try:
            p = workdir / f"sound{i}.mp3"
            download(found["previews"]["preview-hq-mp3"], p)
            paths.append(p)
            used.add(found["id"])
            credits.append({"freesound_id": found["id"], "name": found["name"],
                            "author": found["username"]})
            history["freesound_ids"].append(found["id"])
            log(f"صوت: {found['name']}")
        except Exception as e:
            log(f"خطأ بتحميل الصوت: {e}")
    if not paths:
        raise RuntimeError("ما حصلنا أي صوت")
    return paths, credits


VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def next_local_clip(history):
    """أول فيديو بمجلد clips ما انستخدم قبل"""
    used = set(history.setdefault("local_clips", []))
    if not CLIPS_DIR.exists():
        return None
    files = sorted(f for f in CLIPS_DIR.iterdir()
                   if f.suffix.lower() in VIDEO_EXT and f.name not in used)
    return files[0] if files else None


def theme_from_name(path):
    name = path.stem.replace("-", " ").replace("_", " ")
    return " ".join(w for w in name.split() if not w.isdigit()).strip() or "satisfying asmr"


def has_audio(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                          "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True)
    return bool(out.stdout.strip())


MUSIC_TERMS = (["upbeat electronic loop", "drum loop", "trap beat", "edm loop", "hip hop beat"]
               if STYLE == "energetic" else
               ["calm piano loop", "lofi loop", "music box", "ambient pad", "soft piano"])


def get_sfx(term, history, workdir, name):
    try:
        res = freesound_search(term, history, 0)
    except Exception:
        return None
    res = [x for x in res if x.get("duration", 9) <= 3] or res
    if not res:
        return None
    x = random.choice(res[:8])
    p = workdir / name
    download(x["previews"]["preview-hq-mp3"], p)
    return p


def get_music(history, workdir):
    if not MUSIC_ENABLED or not FREESOUND_API_KEY:
        return None, None
    terms = MUSIC_TERMS[:]
    random.shuffle(terms)
    for t in terms:
        try:
            res = freesound_search(t, history, 20)
        except Exception:
            continue
        if res:
            m = random.choice(res[:10])
            p = workdir / "music.mp3"
            download(m["previews"]["preview-hq-mp3"], p)
            history["freesound_ids"].append(m["id"])
            log(f"موسيقى: {m['name']}")
            return p, {"freesound_id": m["id"], "name": m["name"], "author": m["username"]}
    return None, None


# ------------------------- 4) الهمس -------------------------
def make_whisper(text, workdir):
    if not VOICE_ENABLED or not text:
        return None
    try:
        import edge_tts
        path = workdir / "voice.mp3"
        # تبطيء + خفض النبرة والصوت = إحساس همس ناعم
        comm = edge_tts.Communicate(text, VOICE, rate="-30%", pitch="-6Hz", volume="-25%")
        asyncio.run(comm.save(str(path)))
        log("تم توليد صوت الهمس")
        return path
    except Exception as e:
        log(f"الهمس فشل ({e})، نكمل بدونه")
        return None


# ------------------------- 5) التركيب -------------------------
def find_font():
    for f in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
              "C:/Windows/Fonts/arialbd.ttf", "/Library/Fonts/Arial Bold.ttf"]:
        if Path(f).exists():
            return f
    return None


def clip_duration(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(path)], capture_output=True, text=True)
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def choose_duration(clips):
    """مدة عشوائية بين الأقل والأكثر. بمقطع واحد ما تتجاوز طوله حتى ما يبين التكرار"""
    clips = clips if isinstance(clips, list) else [clips]
    target = random.uniform(VIDEO_MIN_SECONDS, VIDEO_SECONDS)
    if len(clips) == 1:
        real = clip_duration(clips[0])
        if real > 0:
            target = min(target, real - 0.2)
    return round(max(target, min(VIDEO_MIN_SECONDS, VIDEO_SECONDS)), 1)


def build_video(clips, sounds, voice, out_path, seconds=None, hook=None, music=None, whoosh=None):
    clips = clips if isinstance(clips, list) else [clips]
    n = len(clips)
    D = seconds or choose_duration(clips)
    seg = D / n
    log(f"مدة الفيديو: {D} ثانية | عدد اللقطات: {n}")
    hook_filter = ""
    font = find_font()
    if hook and HOOK_TEXT_ENABLED and font:
        # نكتب النص بملف حتى نتجنب مشاكل الرموز الخاصة
        hook_file = Path(out_path).parent / "hook.txt"
        clean = "".join(ch for ch in hook if ord(ch) < 0x2000).strip()
        hook_file.write_text(clean, encoding="utf-8")
        ff = font.replace(":", "\\:")
        hf = str(hook_file).replace(":", "\\:")
        hook_filter = (f",drawtext=fontfile='{ff}':textfile='{hf}':fontsize=58:"
                       f"fontcolor=white:borderw=6:bordercolor=black@0.8:"
                       f"x=(w-text_w)/2:y=h*0.18:enable='lt(t,3)':"
                       f"alpha='if(lt(t,2.5),1,(3-t)/0.5)'")

    energetic = STYLE == "energetic"
    color = ("eq=contrast=1.12:saturation=1.3:brightness=0.02,unsharp=5:5:0.6"
             if energetic else
             "eq=brightness=-0.03:saturation=0.9,colorbalance=rs=0.06:gs=0.02:bs=-0.06")
    # زوم تدريجي لداخل كل لقطة (punch-in) يعطي إحساس حركة
    frames = max(1, int(seg * 30))
    zoom = (f",zoompan=z='1+0.12*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s=1080x1920:fps=30" if energetic else "")

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for c in clips:
        cmd += ["-stream_loop", "-1", "-i", str(c)]
    idx = n
    sound_idx = []
    for s_ in sounds:
        cmd += ["-stream_loop", "-1", "-i", str(s_)]
        sound_idx.append(idx); idx += 1
    voice_idx = music_idx = None
    if voice:
        cmd += ["-i", str(voice)]; voice_idx = idx; idx += 1
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]; music_idx = idx; idx += 1
    whoosh_idx = []
    if whoosh and n > 1:
        for _ in range(n - 1):
            cmd += ["-i", str(whoosh)]; whoosh_idx.append(idx); idx += 1
    clip_audio = n == 1 and has_audio(clips[0])

    fmt = "aformat=sample_rates=44100:channel_layouts=stereo"
    parts, vlabels = [], []
    for i, c in enumerate(clips):
        real = clip_duration(c)
        start = max(0.0, (real - seg) / 2) if (n > 1 and real > seg) else 0.0
        parts.append(
            f"[{i}:v]trim=start={start:.2f}:duration={seg:.2f},setpts=PTS-STARTPTS,"
            f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30"
            f"{zoom},{color},setsar=1[v{i}]")
        vlabels.append(f"[v{i}]")
    joined = f"{''.join(vlabels)}concat=n={n}:v=1:a=0" if n > 1 else "[v0]null"
    # بدون تلاشي بالنهاية حتى الفيديو يلف (loop) بسلاسة ويعيدونه
    parts.append(f"{joined},fade=t=in:st=0:d=0.15{hook_filter},format=yuv420p[v]")

    labels = []
    vols = [1.0, 0.6, 0.4]
    if clip_audio:
        parts.append(f"[0:a]{fmt},volume=1.0[ca]")
        labels.append("[ca]")
        vols = [0.35, 0.25, 0.2]
    for k, si in enumerate(sound_idx):
        parts.append(f"[{si}:a]{fmt},volume={vols[k]}[a{k}]")
        labels.append(f"[a{k}]")
    if voice_idx is not None:
        parts.append(f"[{voice_idx}:a]{fmt},highpass=f=100,lowpass=f=9000,"
                     f"aecho=0.8:0.6:45:0.2,volume=1.8,adelay=400|400[vo]")
        labels.append("[vo]")
    if music_idx is not None:
        parts.append(f"[{music_idx}:a]{fmt},volume={MUSIC_VOLUME}[mu]")
        labels.append("[mu]")
    for k, wi in enumerate(whoosh_idx):
        ms = max(0, int(((k + 1) * seg - 0.25) * 1000))
        parts.append(f"[{wi}:a]{fmt},volume=0.7,adelay={ms}|{ms}[w{k}]")
        labels.append(f"[w{k}]")
    parts.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"afade=t=in:st=0:d=0.1,afade=t=out:st={D-0.3:.2f}:d=0.3,alimiter=limit=0.9[a]")

    cmd += ["-filter_complex", ";".join(parts),
            "-map", "[v]", "-map", "[a]", "-t", str(D),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(out_path)]
    subprocess.run(cmd, check=True)
    log(f"الفيديو جاهز: {out_path}")
    return out_path


# ------------------------- التشغيل الرئيسي -------------------------
def main():
    history = load_history()
    workdir = OUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    workdir.mkdir(parents=True, exist_ok=True)

    local = next_local_clip(history)
    if local:
        theme = theme_from_name(local)
        log(f"نستخدم فيديو من مجلد clips: {local.name} ({theme})")
        idea = get_idea(history, forced_theme=theme)
        clip = [local]
        video_credit = {"author": "Original", "source": "own clip", "query": None}
        history["local_clips"].append(local.name)
    else:
        idea = get_idea(history)
        clip, video_credit = get_video(idea["pexels_query"], history, workdir)
    if video_credit.get("query") and video_credit["query"] != idea["pexels_query"] \
            and video_credit["query"] in SATISFYING:
        # الفيديو تغيّر، فنخلي الأصوات تناسبه
        idea["sounds"] = SATISFYING[video_credit["query"]][1]
        idea["pexels_query"] = video_credit["query"]
    sounds, sound_credits = get_freesound(idea["sounds"], history, workdir,
                                         video_credit.get("query") or idea["pexels_query"])
    voice = make_whisper(idea.get("whisper", ""), workdir)
    music, music_credit = get_music(history, workdir)
    whoosh = get_sfx("whoosh", history, workdir, "whoosh.mp3") if (
        STYLE == "energetic" and len(clip) > 1) else None

    seconds = choose_duration(clip)
    video_desc = video_credit.get("tags") or idea.get("pexels_query") or idea.get("theme")
    if video_credit.get("source") == "own clip":
        video_desc = idea.get("theme") or idea.get("pexels_query")
    idea = write_copy(idea, f"{video_desc} (category: {idea.get('pexels_query')})", seconds, history)

    video_path = build_video(clip, sounds, voice, workdir / "video.mp4", seconds=seconds,
                             hook=idea.get("hook"), music=music, whoosh=whoosh)

    credits_text = ""
    if video_credit["source"] != "own clip":
        credits_text += f"\n\nVideo: {video_credit['author']} ({video_credit['source']})"
    else:
        credits_text += "\n"
    credits_text += "".join(f"\nSound: {c['author']} (Freesound)" for c in sound_credits)
    if music_credit:
        credits_text += f"\nMusic: {music_credit['author']} (Freesound)"
    if voice:
        credits_text += "\nVoice: AI-generated"
    meta = {
        "title": idea["title"][:100],
        "description": idea["description"] + "\n\n" + " ".join(idea["hashtags"]) + credits_text,
        "hashtags": idea["hashtags"],
        "video_file": str(video_path),
        "ai_voice": bool(voice),
        "ai_generated": bool(voice) or (local is not None and CLIPS_ARE_AI),
        "credits": {"video": video_credit, "sounds": sound_credits},
        "created_at": datetime.now().isoformat(),
    }
    (workdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                       encoding="utf-8")

    # نحذف الملفات المؤقتة ونخلي الفيديو والوصف بس
    for f in workdir.iterdir():
        if f.name not in ("video.mp4", "meta.json"):
            f.unlink()

    history["titles"].append(idea["title"])
    save_history(history)
    log("✅ خلصنا")
    return meta


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ فشل: {e}")
        sys.exit(1)
