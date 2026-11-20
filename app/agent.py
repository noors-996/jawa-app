"""The assistant behind the app: Claude with Instagram + schedule tools."""
import base64
import json
from datetime import datetime

from . import config, db, ig, posts

SYSTEM = f"""إنت المساعد اللي جوا تطبيق "{config.APP_NAME}" الخاص بصاحب معاصر جاوا (حساب انستغرام @{config.IG_USERNAME}).
بتحكي مع صاحب المعصرة نفسه. احكي دايماً باللهجة الأردنية البسيطة، جمل قصيرة، بدون كلام رسمي أو تقني.

معلومات المعصرة (استعمل هدول بس، وأبداً ما تألف إشي):
{config.BUSINESS_FACTS}

شو بتقدر تعمل:
- تشوف آخر البوستات والتعليقات والرسائل الخاصة.
- تجهز ردود على التعليقات والرسائل. الرد ما بينبعت إلا لما صاحب المعصرة يكبس "موافق" على البطاقة اللي بتطلع. لهيك استعمل أدوات propose_* واحكيله إنه يوافق.
- تكتب كابشن للبوستات، وتحط البوستات بالجدول، وتعدل وقتها أو تلغيها. النشر الفوري كمان بده موافقة.
- تغير إعدادات مواعيد النشر والرد التلقائي.

أسلوبك مع صاحب المعصرة: صريح ووقح شوي، متل صاحب بيحكيله الحقيقة بوجهه. إذا عمل إشي غلط على الصفحة
(بوست نزّله بدون ما يحكيلك، كابشن ضعيف، توقيت غلط، أسعار بتعليق) احكيله بوضوح إنه غلط وليش، وشو الصح.
وإذا عمل إشي منيح، احكيله إنه منيح بدون مبالغة. بس بدون مسبات أو إهانة، ومع الزباين خليك دايماً مؤدب.

قوانين:
1. الأسعار بالرسائل الخاصة بس، أبداً مش بتعليق عام.
2. ما تجهز ردود على المدح والقلوب والإيموجي.
3. الشكاوي والطلبيات الخاصة والمفاوضة والإشي الحساس: ما تجهزلهم رد، بس احكي لصاحب المعصرة عنهم.
4. أبداً ما تحذف إشي وما تغير إعدادات الحساب.
5. الردود للزباين: لهجة أردنية قصيرة وطبيعية، ونوّع بالكلام.
6. إذا زبون سأل بجد إذا اللي بيرد عليه ذكاء اصطناعي، ما تكذب عليه.
7. إذا طلع خطأ إنه انستغرام وقّف الحساب أو بده تسجيل دخول، وقّف كل إشي واحكي لصاحب المعصرة فوراً.

الكابشن: قصير، لهجة أردنية، فيه سؤال صغير للناس، وبالآخر:
🕒 فاتحين 24 ساعة كل يوم
📞 0789302000
📍 https://maps.app.goo.gl/iqBKj3DHkPxq4thX6
وبعدها 4-5 هاشتاغات مثل #زيت_زيتون #موسم_الزيتون #زيت_بلدي #الأردن #معاصر_جاوا. ما تحط أسعار بالكابشن.

الأوقات كلها بتوقيت عمّان. بالجدول اكتب الوقت بالشكل YYYY-MM-DD HH:MM."""

TOOLS = [
    {"name": "get_recent_posts", "description": "آخر بوستات الحساب مع عدد التعليقات والروابط.",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 8}}}},
    {"name": "get_post_comments", "description": "تعليقات بوست معين مع الردود عليها.",
     "input_schema": {"type": "object", "properties": {"media_id": {"type": "string"}}, "required": ["media_id"]}},
    {"name": "get_dm_conversations", "description": "المحادثات الخاصة وآخر الرسائل بكل وحدة.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "propose_comment_reply", "description": "يجهز رد على تعليق. ما بينبعت إلا بعد موافقة صاحب المعصرة.",
     "input_schema": {"type": "object", "properties": {
         "comment_id": {"type": "string"}, "text": {"type": "string"},
         "username": {"type": "string"}, "comment_text": {"type": "string"}},
         "required": ["comment_id", "text"]}},
    {"name": "propose_dm_reply", "description": "يجهز رسالة خاصة لزبون. ما بتنبعت إلا بعد الموافقة.",
     "input_schema": {"type": "object", "properties": {
         "recipient_id": {"type": "string"}, "text": {"type": "string"},
         "username": {"type": "string"}, "their_message": {"type": "string"}},
         "required": ["recipient_id", "text"]}},
    {"name": "list_media_library", "description": "الصور والفيديوهات المرفوعة على التطبيق.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "schedule_post", "description": "يحط بوست بالجدول. إذا ما في وقت بياخد أقرب موعد فاضي من مواعيد النشر.",
     "input_schema": {"type": "object", "properties": {
         "media_file": {"type": "string"}, "caption": {"type": "string"},
         "when_local": {"type": "string", "description": "YYYY-MM-DD HH:MM بتوقيت عمّان (اختياري)"}},
         "required": ["media_file", "caption"]}},
    {"name": "list_scheduled_posts", "description": "جدول البوستات (الجاية واللي نزلت).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "update_scheduled_post", "description": "يعدل كابشن أو وقت بوست بالجدول.",
     "input_schema": {"type": "object", "properties": {
         "post_id": {"type": "integer"}, "caption": {"type": "string"}, "when_local": {"type": "string"}},
         "required": ["post_id"]}},
    {"name": "cancel_scheduled_post", "description": "يلغي بوست من الجدول (ما بيحذف إشي من انستغرام).",
     "input_schema": {"type": "object", "properties": {"post_id": {"type": "integer"}}, "required": ["post_id"]}},
    {"name": "propose_publish_now", "description": "يجهز نشر بوست من الجدول هلأ. بده موافقة.",
     "input_schema": {"type": "object", "properties": {"post_id": {"type": "integer"}}, "required": ["post_id"]}},
    {"name": "get_owner_notes", "description": "آخر الملاحظات والتنبيهات (من الرد التلقائي والنشر).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_settings", "description": "إعدادات مواعيد النشر والرد التلقائي.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "update_settings", "description": "يغير الإعدادات. المفاتيح: post_slots (قائمة HH:MM)، max_posts_per_day، autoreply_enabled، autoreply_every_hours، autoreply_max_replies (أقصى إشي 4).",
     "input_schema": {"type": "object", "properties": {"values": {"type": "object"}}, "required": ["values"]}},
]


def _propose(kind, payload, summary):
    aid = db.ins("INSERT INTO actions(kind, payload, summary, status, created) VALUES(?,?,?,?,?)",
                 (kind, json.dumps(payload, ensure_ascii=False), summary, "pending", db.now_iso()))
    return {"action_id": aid, "status": "بانتظار موافقة صاحب المعصرة على البطاقة"}


def run_tool(name, a):
    if name == "get_recent_posts":
        return ig.recent_posts(a.get("limit", 8))
    if name == "get_post_comments":
        return ig.comments(a["media_id"])
    if name == "get_dm_conversations":
        out = []
        for c in ig.conversations():
            try:
                msgs = ig.messages(c["id"], 5)
            except (ig.InstagramError,) as e:
                msgs = [{"error": str(e)[:100]}]
            out.append({"conversation": c, "latest_messages": msgs})
        return out
    if name == "propose_comment_reply":
        if db.is_handled(a["comment_id"]):
            return {"error": "هاد التعليق انرد عليه قبل"}
        return _propose("comment_reply", {"comment_id": a["comment_id"], "text": a["text"]},
                        f"رد على تعليق @{a.get('username','')}: «{a.get('comment_text','')}»\n➜ {a['text']}")
    if name == "propose_dm_reply":
        return _propose("dm_reply", {"recipient_id": a["recipient_id"], "text": a["text"]},
                        f"رسالة خاصة لـ @{a.get('username','')}: «{a.get('their_message','')}»\n➜ {a['text']}")
    if name == "list_media_library":
        used = {r["media_file"] for r in db.q("SELECT media_file FROM posts WHERE status!='cancelled'")}
        files = sorted(config.MEDIA_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"file": f.name, "type": posts.media_type_for(f.name), "used": f.name in used} for f in files[:40]]
    if name == "schedule_post":
        return posts.schedule(a["media_file"], a["caption"], a.get("when_local"))
    if name == "list_scheduled_posts":
        return posts.listing()
    if name == "update_scheduled_post":
        return posts.update(int(a["post_id"]), a.get("caption"), a.get("when_local"))
    if name == "cancel_scheduled_post":
        posts.cancel(int(a["post_id"]))
        return {"ok": True}
    if name == "propose_publish_now":
        p = db.q("SELECT * FROM posts WHERE id=?", (int(a["post_id"]),), one=True)
        if not p:
            return {"error": "ما لقيت البوست"}
        return _propose("publish_now", {"post_id": p["id"]}, f"نشر هلأ: {p['caption'][:80]}…")
    if name == "get_owner_notes":
        return db.q("SELECT text, link, created FROM notes ORDER BY id DESC LIMIT 15")
    if name == "get_settings":
        return db.get_settings()
    if name == "update_settings":
        v = dict(a["values"])
        v.pop("paused", None)
        if "autoreply_max_replies" in v:
            v["autoreply_max_replies"] = max(0, min(4, int(v["autoreply_max_replies"])))
        return db.set_settings(v)
    return {"error": "أداة مش معروفة"}


def execute_action(action_id: int) -> str:
    """Owner pressed 'موافق' on a card."""
    act = db.q("SELECT * FROM actions WHERE id=?", (action_id,), one=True)
    if not act or act["status"] != "pending":
        return "هاد الطلب انتهى"
    if db.get_settings().get("paused"):
        return "الحساب موقف مؤقتاً بسبب تنبيه من انستغرام. شغله من الإعدادات بعد ما تتأكد."
    p = json.loads(act["payload"])
    try:
        if act["kind"] == "comment_reply":
            ig.reply_comment(p["comment_id"], p["text"])
            db.mark_handled(p["comment_id"], "comment")
            result = "انبعت الرد ✅"
        elif act["kind"] == "dm_reply":
            ig.send_dm(p["recipient_id"], p["text"])
            result = "انبعتت الرسالة ✅"
        elif act["kind"] == "publish_now":
            posts.publish_post(int(p["post_id"]))
            row = db.q("SELECT status, permalink FROM posts WHERE id=?", (p["post_id"],), one=True)
            result = "نزل البوست ✅" if row and row["status"] == "published" else "ما زبط النشر ❌"
        else:
            result = "نوع مش معروف"
        status = "done"
    except ig.WindowClosed:
        result, status = "ما بنقدر نبعتله، صارله أكتر من 24 ساعة ما راسلنا. رد عليه من التطبيق الأصلي.", "failed"
    except ig.InstagramStop:
        db.set_settings({"paused": True})
        db.add_note("⛔ انستغرام طلب تحقق أو تسجيل دخول. وقّفت كل إشي.")
        result, status = "⛔ انستغرام وقّف الحساب أو طلب تحقق. وقفت كل إشي، فوت على انستغرام وتأكد.", "failed"
    except Exception as e:
        result, status = f"ما زبط: {str(e)[:150]}", "failed"
    db.q("UPDATE actions SET status=?, result=? WHERE id=?", (status, result, action_id))
    return result


def _history(limit=30):
    rows = db.q("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,))[::-1]
    msgs = [{"role": r["role"], "content": _strip_thinking(json.loads(r["content"]))} for r in rows]
    msgs = [m for m in msgs if m["content"]]
    # history must start with a plain user message
    while msgs and not (msgs[0]["role"] == "user" and isinstance(msgs[0]["content"], str)):
        msgs.pop(0)
    # drop any tool call that never got its result (e.g. a crash mid-turn)
    clean = []
    for i, m in enumerate(msgs):
        has_tool = m["role"] == "assistant" and isinstance(m["content"], list) and \
            any(b.get("type") == "tool_use" for b in m["content"])
        nxt = msgs[i + 1] if i + 1 < len(msgs) else None
        if has_tool and not (nxt and nxt["role"] == "user" and isinstance(nxt["content"], list)):
            continue
        if m["role"] == "user" and isinstance(m["content"], list) and (not clean or clean[-1]["role"] != "assistant"):
            continue
        if clean and clean[-1]["role"] == m["role"]:
            continue
        clean.append(m)
    return clean


def _strip_thinking(content):
    """Thinking blocks are only valid inside the request that made them; never replay old ones."""
    if isinstance(content, list):
        return [b for b in content if not (isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking"))]
    return content


def _save(role, content):
    content = _strip_thinking(content)
    if not content:
        return
    db.ins("INSERT INTO messages(role, content, created) VALUES(?,?,?)",
           (role, json.dumps(content, ensure_ascii=False), db.now_iso()))


def chat(user_text: str, image_file: str | None = None) -> dict:
    """Returns {'reply': str, 'actions': [...]}"""
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    now = datetime.now(posts.TZ).strftime("%A %Y-%m-%d %H:%M")
    system = SYSTEM + f"\n\nالوقت هلأ بعمّان: {now}"

    text = user_text
    if image_file:
        text = f"{user_text}\n[رفعت ملف على مكتبة الصور اسمه: {image_file}]"
    msgs = _history()
    msgs.append({"role": "user", "content": text})
    _save("user", text)

    # attach the actual image (only for this turn)
    current = msgs[-1]
    if image_file and posts.media_type_for(image_file) == "IMAGE":
        data = base64.standard_b64encode((config.MEDIA_DIR / image_file).read_bytes()).decode()
        current["content"] = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                              {"type": "text", "text": text}]

    new_actions = []
    for _ in range(10):
        resp = client.messages.create(model=config.MODEL, max_tokens=2000, system=system, tools=TOOLS, messages=msgs)
        content = [b.model_dump(exclude_none=True) for b in resp.content]
        msgs.append({"role": "assistant", "content": content})
        _save("assistant", content)
        if resp.stop_reason != "tool_use":
            break
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            try:
                out = run_tool(b.name, b.input)
                if isinstance(out, dict) and out.get("action_id"):
                    new_actions.append(out["action_id"])
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(out, ensure_ascii=False, default=str)[:15000]})
            except ig.InstagramStop as e:
                db.set_settings({"paused": True})
                db.add_note("⛔ انستغرام طلب تحقق أو تسجيل دخول. وقّفت كل إشي.")
                results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                "content": f"STOP: Instagram blocked/needs login. Stop and tell the owner. {e}"})
            except Exception as e:
                results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True, "content": str(e)[:500]})
        msgs.append({"role": "user", "content": results})
        _save("user", results)

    reply = "".join(b.get("text", "") for b in msgs[-1]["content"] if isinstance(b, dict) and b.get("type") == "text") \
        if msgs[-1]["role"] == "assistant" else ""
    actions = [db.q("SELECT id, kind, summary, status FROM actions WHERE id=?", (i,), one=True) for i in new_actions]
    return {"reply": reply or "تمام 👍", "actions": [a for a in actions if a]}
