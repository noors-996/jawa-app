"""Automatic replies to IMPORTANT customer questions only, paced like a person."""
import json
import random
import time
from datetime import datetime, timedelta, timezone

from . import config, db, ig, posts

PROMPT = f"""إنت بتساعد صاحب معاصر جاوا يرد على أسئلة الزباين المهمة بس على انستغرام.
معلومات المعصرة (استعمل هدول بس، ما تألف إشي):
{config.BUSINESS_FACTS}

لكل عنصر قرر:
- "reply": سؤال حقيقي عن السعر أو الموقع أو الدوام أو كيف يطلب. اكتب رد قصير بلهجة أردنية بسيطة وطبيعية، ونوّع بالكلام.
  * بالتعليقات: أبداً ما تكتب أسعار. لسؤال السعر اعزمه عالخاص أو الاتصال، مثل: "أهلاً فيك 🌿 راسلنا خاص أو اتصل على 0789302000 🫒" بس غيّر الكلام شوي.
  * بالخاص: مسموح الأسعار.
- "owner": شكوى، طلبية محددة، مفاوضة، إشي حساس، سبام، كلام قليل أدب، ريل أو صورة بدون كلام، أو سؤال ما بتقدر تجاوبه من المعلومات. اكتب سبب قصير.
- "ignore": مدح، قلوب، إيموجي، مجاملات عامة.
ما تحكي إنك ذكاء اصطناعي إلا إذا حدا سأل مباشرة، وساعتها لا تكذب.

رجّع JSON بس، بالشكل: {{"items":[{{"id":"...","decision":"reply|owner|ignore","text":"الرد إذا reply","reason":"السبب إذا owner"}}]}}"""


def _in_quiet_hours(s) -> bool:
    now = datetime.now(posts.TZ).strftime("%H:%M")
    a, b = s["autoreply_quiet_from"], s["autoreply_quiet_to"]
    return (a <= now < b) if a <= b else (now >= a or now < b)


def _collect():
    items = []
    since = datetime.now(timezone.utc) - timedelta(days=7)
    for p in ig.recent_posts(8):
        if not p.get("comments_count"):
            continue
        for c in ig.comments(p["id"]):
            if c.get("parent_id") or c.get("username") == config.IG_USERNAME or db.is_handled(c["id"]):
                continue
            replied = any(r.get("username") == config.IG_USERNAME or not r.get("username")
                          for r in ((c.get("replies") or {}).get("data") or []))
            if replied:
                db.mark_handled(c["id"], "comment")
                continue
            ts = c.get("timestamp", "").replace("+0000", "+00:00")
            if ts and datetime.fromisoformat(ts) < since:
                continue
            items.append({"id": c["id"], "kind": "comment", "who": c.get("username", ""),
                          "text": c.get("text", ""), "link": p.get("permalink", "")})
    for conv in ig.conversations():
        msgs = sorted(ig.messages(conv["id"], 5), key=lambda m: m.get("created_time", ""), reverse=True)
        if not msgs:
            continue
        last = msgs[0]
        sender = last.get("from") or {}
        if sender.get("username") == config.IG_USERNAME or db.is_handled(last["id"]):
            continue
        items.append({"id": last["id"], "kind": "dm", "who": sender.get("username", ""),
                      "recipient_id": sender.get("id"), "text": last.get("message") or "",
                      "has_attachment": not last.get("message"), "link": ""})
    return items


def _decide(items):
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    payload = [{"id": i["id"], "where": "تعليق عام" if i["kind"] == "comment" else "رسالة خاصة",
                "text": i["text"] or "(ريل أو صورة بدون كلام)"} for i in items]
    resp = client.messages.create(model=config.MODEL, max_tokens=3000, system=PROMPT,
                                  messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
    raw = "".join(b.text for b in resp.content if b.type == "text")
    raw = raw[raw.find("{"): raw.rfind("}") + 1]
    return {d["id"]: d for d in json.loads(raw).get("items", [])}


def run_once() -> str:
    s = db.get_settings()
    if s.get("paused"):
        return "paused"
    try:
        items = _collect()
        if not items:
            return "ما في إشي جديد"
        decisions = _decide(items)
    except ig.InstagramStop as e:
        db.set_settings({"paused": True})
        db.add_note(f"⛔ انستغرام طلب تحقق أو تسجيل دخول، وقّفت الرد التلقائي والنشر. ({str(e)[:80]})")
        return "stopped"

    max_replies = min(4, int(s["autoreply_max_replies"]))
    sent = 0
    for it in items:
        d = decisions.get(it["id"], {"decision": "owner", "reason": "ما قدرت أقرر"})
        if d["decision"] == "ignore":
            db.mark_handled(it["id"], it["kind"])
        elif d["decision"] == "owner" or (it["kind"] == "dm" and it.get("has_attachment")):
            db.add_note(f"👤 @{it['who']} ({'تعليق' if it['kind']=='comment' else 'خاص'}): «{it['text'] or 'ريل/صورة'}» — {d.get('reason','')}",
                        it["link"])
            db.mark_handled(it["id"], it["kind"])
        elif d["decision"] == "reply" and d.get("text"):
            if sent >= max_replies:
                continue  # leave it for the next run
            if sent > 0:
                time.sleep(random.randint(60, 150))
            try:
                if it["kind"] == "comment":
                    ig.reply_comment(it["id"], d["text"][:300])
                else:
                    ig.send_dm(it["recipient_id"], d["text"])
                sent += 1
                db.mark_handled(it["id"], it["kind"])
            except ig.WindowClosed:
                db.add_note(f"✉️ ما قدرت أرد على @{it['who']} بالخاص (صارله أكتر من يوم). «{it['text']}»")
                db.mark_handled(it["id"], it["kind"])
            except ig.InstagramStop as e:
                db.set_settings({"paused": True})
                db.add_note(f"⛔ انستغرام طلب تحقق أو تسجيل دخول، وقّفت كل إشي. ({str(e)[:80]})")
                return "stopped"
            except Exception as e:
                db.add_note(f"❌ ما زبط الرد على @{it['who']}: {str(e)[:80]}")
    if sent:
        db.add_note(f"🤖 الرد التلقائي بعت {sent} رد.")
    return f"sent {sent}"
