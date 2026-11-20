"""Notices posts the owner put up straight on Instagram (not through the app),
asks him why, and tells him frankly whether it was a good move."""
import base64
import json
import urllib.request
from datetime import datetime, timezone

from . import agent, config, db, ig, posts

REVIEW_PROMPT = """صاحب المعصرة نزّل هالبوست على انستغرام **مباشرة، بدون ما يحكيلك**.
بدي إياك تكون صريح ووقح معه شوي، متل صاحب بيحكيله الحقيقة بوجهه، بس بدون مسبات أو إهانة:
1. اسأله بأول سطر: ليش نزلته من وراك؟ (بأسلوب خفيف ومستفز شوي)
2. احكيله رأيك بصراحة: **صح ولا غلط إنه نزل**؟ احكم حكم واضح بكلمة وحدة بالأول (✅ صح / ⚠️ نص نص / ❌ غلط).
3. وبعدين أسباب قصيرة (3 نقاط بالكثير): جودة الصورة أو الفيديو، الكابشن (فيه تلفون وموقع وهاشتاغات؟ فيه سؤال للناس؟)،
   التوقيت (مقارنة بمواعيد النشر)، وإذا نزّل أكتر من اللازم بنفس اليوم.
4. إذا الكابشن فيه أسعار: هاي غلطة كبيرة، الأسعار بالخاص بس. احكيله إياها بوضوح.
5. سطر أخير: شو كان لازم يعمل بداله، أو شو يعمل هلأ (مثلاً يعدل الكابشن من انستغرام).
خليها قصيرة، لهجة أردنية، بدون مقدمات."""


def _image_block(item):
    url = item.get("thumbnail_url") if item.get("media_type") == "VIDEO" else item.get("media_url")
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            ctype = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0]
            data = r.read()
    except Exception:
        return None
    if ctype not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        ctype = "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": ctype,
                                        "data": base64.standard_b64encode(data).decode()}}


def _app_permalinks():
    return {r["permalink"] for r in db.q("SELECT permalink FROM posts WHERE permalink IS NOT NULL AND permalink != ''")}


def _same_day_count(items, ts):
    d = datetime.fromisoformat(ts.replace("+0000", "+00:00")).astimezone(posts.TZ).date()
    return sum(1 for i in items if i.get("timestamp") and
               datetime.fromisoformat(i["timestamp"].replace("+0000", "+00:00")).astimezone(posts.TZ).date() == d)


def _review(item, items):
    import anthropic
    s = db.get_settings()
    local = posts.to_local_str(item["timestamp"].replace("+0000", "+00:00"))
    facts = {
        "النوع": item.get("media_product_type") or item.get("media_type"),
        "نزل الساعة (عمّان)": local,
        "مواعيد النشر المعتمدة": s["post_slots"],
        "الحد الأقصى باليوم": s["max_posts_per_day"],
        "عدد البوستات اللي نزلت بنفس اليوم": _same_day_count(items, item["timestamp"]),
        "الكابشن": item.get("caption") or "(بدون كابشن)",
        "الرابط": item.get("permalink"),
    }
    content = [{"type": "text", "text": REVIEW_PROMPT + "\n\nمعلومات البوست:\n" +
                json.dumps(facts, ensure_ascii=False, indent=1)}]
    img = _image_block(item)
    if img:
        content.insert(0, img)
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(model=config.MODEL, max_tokens=900, system=agent.SYSTEM,
                                  messages=[{"role": "user", "content": content}])
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def check_new_posts():
    """Run every few minutes. Reviews at most 2 new outside posts per run."""
    if config.DEMO_MODE or db.get_settings().get("paused") or not config.ANTHROPIC_API_KEY:
        return
    items = ig.recent_posts(10, extra_fields="media_type,media_url,thumbnail_url")
    seeded = db.q("SELECT 1 FROM settings WHERE key='reviews_seeded'", one=True)
    if not seeded:  # first run: don't review the whole old feed, only what comes after now
        for it in items:
            db.mark_handled(f"review:{it['id']}", "review")
        db.ins("INSERT OR REPLACE INTO settings(key, value) VALUES('reviews_seeded', 'true')")
        return
    from_app = _app_permalinks()
    done = 0
    for it in sorted(items, key=lambda i: i.get("timestamp") or ""):
        key = f"review:{it['id']}"
        if db.is_handled(key):
            continue
        if it.get("permalink") in from_app:  # posted through the app, nothing to ask
            db.mark_handled(key, "review")
            continue
        if done >= 2:
            break
        text = _review(it, items)
        db.mark_handled(key, "review")
        if not text:
            continue
        agent._save("user", f"📢 نزل بوست جديد على الصفحة من برا التطبيق: {it.get('permalink', '')}")
        agent._save("assistant", [{"type": "text", "text": text}])
        db.add_note("👀 نزّلت بوست بدون ما تحكيلي، شوف شو رأيي بالمحادثة", it.get("permalink", ""))
        done += 1
