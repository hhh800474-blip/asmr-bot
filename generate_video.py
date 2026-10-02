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

VIDEO_SECONDS = int(os.getenv("VIDEO_SECONDS", "15"))      # قصير = نسبة مشاهدة كاملة أعلى
HOOK_TEXT_ENABLED = os.getenv("HOOK_TEXT_ENABLED", "1") == "1"
CONTENT_LANG = os.getenv("CONTENT_LANG", "en")             # en أو ar
VOICE = os.getenv("VOICE", "en-US-AriaNeural")             # للعربي: ar-SA-ZariyahNeural
VOICE_ENABLED = os.getenv("VOICE_ENABLED", "1") == "1"

BASE = Path(__file__).parent
OUT_ROOT = BASE / "output"
HISTORY_FILE = BASE / "history.json"

# أفكار احتياطية إذا Gemini ما اشتغل
PRESETS = [
    {"theme": "cutting soap cubes", "pexels_query": "cutting soap",
     "sounds": ["soap cutting crunch", "knife cutting"], "hook": "Wait for the last cut..."},
    {"theme": "crunchy ice", "pexels_query": "ice cubes close up",
     "sounds": ["ice crunch", "ice cubes glass"], "hook": "The final crunch is unreal"},
    {"theme": "kinetic sand slicing", "pexels_query": "kinetic sand",
     "sounds": ["sand crunch", "cutting sand"], "hook": "Listen closely..."},
    {"theme": "honey dripping", "pexels_query": "honey dripping",
     "sounds": ["sticky liquid pour", "honey"], "hook": "You'll watch this twice"},
    {"theme": "slime pressing", "pexels_query": "slime hands",
     "sounds": ["slime squish", "squishy"], "hook": "Turn your sound on 🔊"},
    {"theme": "pouring coffee over ice", "pexels_query": "iced coffee pouring",
     "sounds": ["pouring liquid glass", "ice crackle"], "hook": "Wait for the pour..."},
    {"theme": "match striking in the dark", "pexels_query": "match fire close up",
     "sounds": ["match strike", "candle flame"], "hook": "Only 1% hear the last sound"},
    {"theme": "rain tapping on glass", "pexels_query": "raindrops glass macro",
     "sounds": ["rain on window close", "tapping glass"], "hook": "Headphones on... trust me"},
]


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
def get_idea(history):
    preset = random.choice(PRESETS)
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
    recent = history["titles"][-20:]
    prompt = f"""You create ideas for faceless ASMR short videos, max 15 seconds,
designed so viewers watch until the very end and replay.
Focus on crisp "oddly satisfying" triggers with a clear close-up action:
cutting, crunching, pouring, dripping, tapping, peeling, squishing, crackling.
Avoid repeating these recent titles: {recent}
Return ONLY JSON with these keys:
- theme: short scene in English
- pexels_query: 2-3 English words for a close-up stock video of the action (no faces)
- sounds: list of 2 English search terms for crisp trigger sound effects
- hook: on-screen text for the first 3 seconds, in English, max 6 words,
  creates curiosity (e.g. "Wait for the last crunch..."), no emoji
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
            log(f"الفكرة ({model}): {idea['title']}")
            return idea
        except Exception as e:
            log(f"Gemini {model} فشل ({str(e)[:150]})")
    log("نستخدم فكرة جاهزة")
    return fallback


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


def get_pixabay_video(query, history, workdir):
    if not PIXABAY_API_KEY:
        raise RuntimeError("PIXABAY_API_KEY مفقود")
    r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
        "key": PIXABAY_API_KEY, "q": query, "per_page": 50,
        "safesearch": "true", "video_type": "film"})
    r.raise_for_status()
    hits = [h for h in r.json().get("hits", [])
            if f"pb{h['id']}" not in history["pexels_ids"] and h.get("duration", 0) >= 5]
    if not hits:
        # نجرب بأول كلمة بس إذا البحث ضيق
        short = query.split()[0]
        if short != query:
            return get_pixabay_video(short, history, workdir)
        raise RuntimeError(f"ما لقينا فيديو لـ: {query}")

    def pick_file(h):
        files = [f for f in h["videos"].values() if f.get("url")]
        vertical = [f for f in files if f["height"] > f["width"]]
        pool = vertical or files
        return max(pool, key=lambda f: f["width"] * f["height"]), bool(vertical)

    # نفضّل الفيديوهات العمودية
    scored = [(h, *pick_file(h)) for h in hits]
    vertical = [x for x in scored if x[2]]
    h, f, _ = random.choice((vertical or scored)[:10])

    path = workdir / "clip.mp4"
    download(f["url"], path)
    history["pexels_ids"].append(f"pb{h['id']}")
    log(f"فيديو Pixabay #{h['id']} من {h['user']}")
    return path, {"pixabay_id": h["id"], "author": h["user"], "url": h["pageURL"],
                  "source": "Pixabay"}


def get_video(query, history, workdir):
    if PIXABAY_API_KEY:
        return get_pixabay_video(query, history, workdir)
    path, credit = get_pexels_video(query, history, workdir)
    credit["source"] = "Pexels"
    return path, credit


# ------------------------- 3) الأصوات -------------------------
def get_freesound(queries, history, workdir):
    if not FREESOUND_API_KEY:
        raise RuntimeError("FREESOUND_API_KEY مفقود")
    paths, credits = [], []
    for i, q in enumerate(queries[:3]):
        try:
            r = requests.get("https://freesound.org/apiv2/search/text/", timeout=30, params={
                "query": q,
                "filter": 'license:"Creative Commons 0" duration:[15 TO 600]',
                "fields": "id,name,username,previews,duration",
                "page_size": 15,
                "token": FREESOUND_API_KEY,
            })
            r.raise_for_status()
            results = [s for s in r.json().get("results", [])
                       if s["id"] not in history["freesound_ids"]] or r.json().get("results", [])
            if not results:
                log(f"ما لقينا صوت لـ: {q}")
                continue
            s = random.choice(results[:8])
            p = workdir / f"sound{i}.mp3"
            download(s["previews"]["preview-hq-mp3"], p)
            paths.append(p)
            credits.append({"freesound_id": s["id"], "name": s["name"], "author": s["username"]})
            history["freesound_ids"].append(s["id"])
            log(f"صوت: {s['name']}")
        except Exception as e:
            log(f"خطأ بالصوت '{q}': {e}")
    if not paths:
        raise RuntimeError("ما حصلنا أي صوت")
    return paths, credits


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


def build_video(clip, sounds, voice, out_path, seconds=VIDEO_SECONDS, hook=None):
    D = seconds
    hook_filter = ""
    font = find_font()
    if hook and HOOK_TEXT_ENABLED and font:
        # نكتب النص بملف حتى نتجنب مشاكل الرموز الخاصة
        hook_file = Path(out_path).parent / "hook.txt"
        clean = "".join(ch for ch in hook if ord(ch) < 0x2000).strip()
        hook_file.write_text(clean, encoding="utf-8")
        ff = font.replace(":", "\\:")
        hf = str(hook_file).replace(":", "\\:")
        hook_filter = (f",drawtext=fontfile='{ff}':textfile='{hf}':fontsize=54:"
                       f"fontcolor=white:borderw=5:bordercolor=black@0.7:"
                       f"x=(w-text_w)/2:y=h*0.18:enable='lt(t,3)':"
                       f"alpha='if(lt(t,2.5),1,(3-t)/0.5)'")
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-stream_loop", "-1", "-i", str(clip)]
    for s in sounds:
        cmd += ["-stream_loop", "-1", "-i", str(s)]
    if voice:
        cmd += ["-i", str(voice)]

    fmt = "aformat=sample_rates=44100:channel_layouts=stereo"
    parts = [
        # بدون تلاشي بالنهاية حتى الفيديو يلف (loop) بسلاسة ويعيدونه
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"fps=30,eq=brightness=-0.03:saturation=0.9,"
        f"colorbalance=rs=0.06:gs=0.02:bs=-0.06,"
        f"fade=t=in:st=0:d=0.2{hook_filter},format=yuv420p[v]"
    ]
    labels = []
    vols = [1.0, 0.6, 0.4]
    for i in range(len(sounds)):
        parts.append(f"[{i+1}:a]{fmt},volume={vols[i]}[a{i}]")
        labels.append(f"[a{i}]")
    if voice:
        vi = len(sounds) + 1
        parts.append(
            f"[{vi}:a]{fmt},highpass=f=100,lowpass=f=9000,"
            f"aecho=0.8:0.6:45:0.2,volume=1.8,adelay=400|400[vo]")
        labels.append("[vo]")
    parts.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"afade=t=in:st=0:d=0.15,afade=t=out:st={D-0.4}:d=0.4,alimiter=limit=0.85[a]")

    cmd += ["-filter_complex", ";".join(parts),
            "-map", "[v]", "-map", "[a]", "-t", str(D),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
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

    idea = get_idea(history)
    clip, video_credit = get_video(idea["pexels_query"], history, workdir)
    sounds, sound_credits = get_freesound(idea["sounds"], history, workdir)
    voice = make_whisper(idea.get("whisper", ""), workdir)

    video_path = build_video(clip, sounds, voice, workdir / "video.mp4", hook=idea.get("hook"))

    credits_text = f"\n\nVideo: {video_credit['author']} ({video_credit['source']})"
    credits_text += "".join(f"\nSound: {c['author']} (Freesound)" for c in sound_credits)
    if voice:
        credits_text += "\nVoice: AI-generated"
    meta = {
        "title": idea["title"][:100],
        "description": idea["description"] + "\n\n" + " ".join(idea["hashtags"]) + credits_text,
        "hashtags": idea["hashtags"],
        "video_file": str(video_path),
        "ai_voice": bool(voice),
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
