"""
ينشر آخر فيديو انصنع على يوتيوب + تيك توك + فيسبوك عن طريق Buffer
-------------------------------------------------------------------
1) يرفع الفيديو على استضافة مجانية بدون حساب (catbox / litterbox)
   حتى يصير له رابط عام (Buffer يحتاج رابط)
2) يجيب قنواتك من Buffer تلقائياً (ما تحتاج تكتب IDs)
3) ينشر الفيديو فوراً على كل قناة

المفاتيح المطلوبة (GitHub Secrets):
  BUFFER_API_KEY   من publish.buffer.com/settings/api
  CLOUDINARY_URL   اختياري، إذا موجود يستخدمه أولاً
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

BUFFER_API_KEY = os.getenv("BUFFER_API_KEY", "").strip()
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "").strip()
PLATFORMS = [p.strip() for p in os.getenv("PUBLISH_PLATFORMS", "youtube,tiktok,facebook").split(",") if p.strip()]
YOUTUBE_CATEGORY = os.getenv("YOUTUBE_CATEGORY", "24")   # 24 = Entertainment
BUFFER_URL = "https://api.buffer.com"
VIDEO_URL = os.getenv("VIDEO_URL", "").strip()   # رابط GitHub Pages من ملف التشغيل
OUT_ROOT = Path(__file__).parent / "output"


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ------------------------- آخر فيديو -------------------------
def latest_video():
    dirs = sorted([d for d in OUT_ROOT.glob("*") if (d / "meta.json").exists()])
    if not dirs:
        raise RuntimeError("ما كو فيديو جاهز بمجلد output")
    d = dirs[-1]
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    return d / "video.mp4", meta


# ------------------------- Cloudinary -------------------------
def upload_cloudinary(video_path):
    if not CLOUDINARY_URL.startswith("cloudinary://"):
        raise RuntimeError("CLOUDINARY_URL مفقود أو غلط (لازم يبدي بـ cloudinary://)")
    u = urlparse(CLOUDINARY_URL)
    api_key, api_secret, cloud = u.username, u.password, u.hostname
    ts = str(int(time.time()))
    folder = "asmr-bot"
    to_sign = f"folder={folder}&timestamp={ts}{api_secret}"
    signature = hashlib.sha1(to_sign.encode()).hexdigest()
    with open(video_path, "rb") as f:
        r = requests.post(
            f"https://api.cloudinary.com/v1_1/{cloud}/video/upload",
            data={"api_key": api_key, "timestamp": ts, "folder": folder,
                  "signature": signature},
            files={"file": f}, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"Cloudinary رفض الرفع: {r.status_code} {r.text[:300]}")
    return r.json()["secure_url"]


def upload_catbox(video_path):
    """استضافة دائمة مجانية بدون حساب"""
    with open(video_path, "rb") as f:
        r = requests.post("https://catbox.moe/user/api.php", timeout=300,
                          data={"reqtype": "fileupload"},
                          files={"fileToUpload": (video_path.name, f, "video/mp4")})
    url = r.text.strip()
    if r.status_code != 200 or not url.startswith("https://"):
        raise RuntimeError(f"catbox: {r.status_code} {url[:200]}")
    return url


def upload_litterbox(video_path):
    """استضافة مؤقتة 72 ساعة (تكفي لأن النشر فوري)"""
    with open(video_path, "rb") as f:
        r = requests.post("https://litterbox.catbox.moe/resources/internals/api.php",
                          timeout=300, data={"reqtype": "fileupload", "time": "72h"},
                          files={"fileToUpload": (video_path.name, f, "video/mp4")})
    url = r.text.strip()
    if r.status_code != 200 or not url.startswith("https://"):
        raise RuntimeError(f"litterbox: {r.status_code} {url[:200]}")
    return url


def upload_uguu(video_path):
    """استضافة مؤقتة (3 ساعات) كخطة احتياطية"""
    with open(video_path, "rb") as f:
        r = requests.post("https://uguu.se/upload", timeout=300,
                          files={"files[]": (video_path.name, f, "video/mp4")})
    r.raise_for_status()
    return r.json()["files"][0]["url"]


def url_works(url, tries=1, wait=10):
    for i in range(tries):
        try:
            r = requests.get(url, stream=True, timeout=60, headers={"Range": "bytes=0-1023"})
            ok = r.status_code in (200, 206)
            r.close()
            if ok:
                return True
        except Exception:
            pass
        if i < tries - 1:
            time.sleep(wait)
    return False


def upload_media(video_path):
    # الطريقة الأساسية: الفيديو منشور على GitHub Pages من ملف التشغيل
    if VIDEO_URL:
        log(f"نتأكد من رابط GitHub Pages: {VIDEO_URL}")
        if url_works(VIDEO_URL, tries=12, wait=10):
            log("✅ الرابط شغال")
            return VIDEO_URL
        log("رابط GitHub Pages ما اشتغل، نجرب استضافات ثانية")
    hosts = []
    if CLOUDINARY_URL:
        hosts.append(("Cloudinary", upload_cloudinary))
    hosts += [("catbox", upload_catbox), ("litterbox", upload_litterbox), ("uguu", upload_uguu)]
    for name, fn in hosts:
        try:
            url = fn(video_path)
            if url_works(url):
                log(f"الفيديو صار له رابط عام ({name}): {url}")
                return url
            log(f"{name}: الرابط ما يفتح، نجرب غيره")
        except Exception as e:
            log(f"{name} فشل: {str(e)[:200]}")
    raise RuntimeError("ما گدرنا نرفع الفيديو على أي استضافة")


# ------------------------- Buffer -------------------------
def gql(query, variables=None):
    r = requests.post(BUFFER_URL, timeout=60,
                      headers={"Authorization": f"Bearer {BUFFER_API_KEY}",
                               "Content-Type": "application/json"},
                      json={"query": query, "variables": variables or {}})
    if r.status_code == 401:
        raise RuntimeError("مفتاح Buffer غلط (401)")
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        raise RuntimeError("Buffer: " + "; ".join(e.get("message", "") for e in data["errors"]))
    return data["data"]


def get_channels():
    orgs = gql("query { account { organizations { id name } } }")["account"]["organizations"]
    channels = []
    for org in orgs:
        res = gql("""query Ch($input: ChannelsInput!) {
            channels(input: $input) { id name service isLocked isDisconnected } }""",
                  {"input": {"organizationId": org["id"]}})
        channels += res["channels"]
    for c in channels:
        log(f"قناة: {c['service']} | {c['name']} | مقفولة={c['isLocked']} | مفصولة={c['isDisconnected']}")
    return channels


CREATE_POST = """mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id status } }
    ... on MutationError { message }
  }
}"""


def build_input(channel, video_url, meta):
    service = channel["service"].lower()
    title = meta["title"][:100]
    hashtags = " ".join(meta.get("hashtags", []))
    ai = bool(meta.get("ai_voice"))

    inp = {
        "channelId": channel["id"],
        "schedulingType": "automatic",
        "mode": "shareNow",          # ينشر فوراً
        "aiAssisted": True,
        "assets": [{"video": {"url": video_url}}],
    }
    if service == "youtube":
        inp["text"] = meta["description"]
        inp["metadata"] = {"youtube": {
            "title": title, "categoryId": YOUTUBE_CATEGORY, "privacy": "public",
            "madeForKids": False, "notifySubscribers": True, "isAiGenerated": ai}}
    elif service == "tiktok":
        inp["text"] = f"{title} {hashtags}"[:2000]
        inp["metadata"] = {"tiktok": {"isAiGenerated": ai}}
    elif service == "facebook":
        inp["text"] = f"{title}\n\n{hashtags}"
        inp["metadata"] = {"facebook": {"type": "reel"}}
    else:
        inp["text"] = f"{title}\n\n{hashtags}"
    return inp


def main():
    if not BUFFER_API_KEY:
        raise RuntimeError("BUFFER_API_KEY مفقود")
    video_path, meta = latest_video()
    log(f"ننشر: {meta['title']}")

    channels = [c for c in get_channels()
                if c["service"].lower() in PLATFORMS and not c["isLocked"] and not c["isDisconnected"]]
    if not channels:
        raise RuntimeError("ما لگينا قنوات مربوطة بـ Buffer (يوتيوب/تيك توك/فيسبوك)")

    video_url = upload_media(video_path)

    ok = 0
    for ch in channels:
        try:
            res = gql(CREATE_POST, {"input": build_input(ch, video_url, meta)})["createPost"]
            if res.get("post"):
                ok += 1
                log(f"✅ {ch['service']}: انرسل (post {res['post']['id']})")
            else:
                log(f"❌ {ch['service']}: {res.get('message')}")
        except Exception as e:
            log(f"❌ {ch['service']}: {e}")

    log(f"النتيجة: {ok} من {len(channels)} منصات")
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ فشل النشر: {e}")
        sys.exit(1)
