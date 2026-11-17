"""Post schedule: when posts go out, and publishing them."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, db, ig

TZ = ZoneInfo(config.TIMEZONE)
VIDEO_EXT = (".mp4", ".mov", ".m4v")


def media_type_for(filename: str) -> str:
    return "REELS" if filename.lower().endswith(VIDEO_EXT) else "IMAGE"


def to_local_str(iso_utc: str) -> str:
    return datetime.fromisoformat(iso_utc).astimezone(TZ).strftime("%Y-%m-%d %H:%M")


def parse_local(text: str) -> datetime:
    """'YYYY-MM-DD HH:MM' in Amman time -> aware UTC datetime."""
    dt = datetime.strptime(text.strip().replace("T", " ")[:16], "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=TZ).astimezone(timezone.utc)


def next_free_slot(after: datetime | None = None) -> datetime:
    s = db.get_settings()
    slots = sorted(s["post_slots"]) or ["19:30"]
    max_day = int(s["max_posts_per_day"])
    start = (after or datetime.now(timezone.utc)).astimezone(TZ) + timedelta(minutes=15)
    taken = {r["scheduled_at"] for r in db.q("SELECT scheduled_at FROM posts WHERE status IN ('scheduled','publishing')")}
    taken_local = [datetime.fromisoformat(t).astimezone(TZ) for t in taken]
    for day in range(0, 60):
        d = (start + timedelta(days=day)).date()
        if sum(1 for t in taken_local if t.date() == d) >= max_day:
            continue
        for sl in slots:
            h, m = map(int, sl.split(":"))
            cand = datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)
            if cand < start:
                continue
            if any(abs((cand - t).total_seconds()) < 3600 for t in taken_local):
                continue
            return cand.astimezone(timezone.utc)
    return start.astimezone(timezone.utc)


def view(row: dict) -> dict:
    row = dict(row)
    row["scheduled_local"] = to_local_str(row["scheduled_at"]) if row.get("scheduled_at") else ""
    row["media_url"] = f"/media/{row['media_file']}"
    return row


def schedule(media_file: str, caption: str, when_local: str | None = None) -> dict:
    if not (config.MEDIA_DIR / media_file).exists():
        raise ValueError("الملف مش موجود بمكتبة الصور")
    when = parse_local(when_local) if when_local else next_free_slot()
    if when < datetime.now(timezone.utc):
        raise ValueError("الوقت اللي اخترته فات")
    pid = db.ins("INSERT INTO posts(media_file, media_type, caption, scheduled_at, status, created) VALUES(?,?,?,?,?,?)",
                 (media_file, media_type_for(media_file), caption, when.isoformat(timespec="seconds"),
                  "scheduled", db.now_iso()))
    return view(db.q("SELECT * FROM posts WHERE id=?", (pid,), one=True))


def update(post_id: int, caption: str | None = None, when_local: str | None = None) -> dict:
    p = db.q("SELECT * FROM posts WHERE id=?", (post_id,), one=True)
    if not p or p["status"] != "scheduled":
        raise ValueError("هاد البوست مش بالجدول")
    if caption is not None:
        db.q("UPDATE posts SET caption=? WHERE id=?", (caption, post_id))
    if when_local:
        db.q("UPDATE posts SET scheduled_at=? WHERE id=?", (parse_local(when_local).isoformat(timespec="seconds"), post_id))
    return view(db.q("SELECT * FROM posts WHERE id=?", (post_id,), one=True))


def cancel(post_id: int):
    db.q("UPDATE posts SET status='cancelled' WHERE id=? AND status='scheduled'", (post_id,))


def listing(include_done=True):
    rows = db.q("SELECT * FROM posts WHERE status != 'cancelled' ORDER BY scheduled_at DESC LIMIT 60")
    if not include_done:
        rows = [r for r in rows if r["status"] == "scheduled"]
    return [view(r) for r in rows]


def publish_post(post_id: int):
    p = db.q("SELECT * FROM posts WHERE id=?", (post_id,), one=True)
    if not p or p["status"] not in ("scheduled", "failed"):
        return
    if not config.PUBLIC_BASE_URL and not config.DEMO_MODE:
        db.q("UPDATE posts SET status='failed', error=? WHERE id=?", ("PUBLIC_BASE_URL مش مضبوط", post_id))
        return
    db.q("UPDATE posts SET status='publishing' WHERE id=?", (post_id,))
    url = f"{config.PUBLIC_BASE_URL}/media/{p['media_file']}"
    try:
        res = ig.publish(url, p["media_type"], p["caption"])
        db.q("UPDATE posts SET status='published', permalink=?, error=NULL WHERE id=?", (res.get("permalink", ""), post_id))
        db.add_note(f"✅ نزل البوست: {p['caption'][:40]}…", res.get("permalink", ""))
    except ig.InstagramStop as e:
        db.q("UPDATE posts SET status='failed', error=? WHERE id=?", (str(e)[:300], post_id))
        db.add_note("⛔ انستغرام وقّف الحساب أو طلب تسجيل دخول/تحقق. فوت على انستغرام وتأكد، وما رح ينشر إشي لحد ما تصلح.")
        raise
    except Exception as e:
        db.q("UPDATE posts SET status='failed', error=? WHERE id=?", (str(e)[:300], post_id))
        db.add_note(f"❌ ما زبط نشر البوست: {p['caption'][:40]}…")


def publish_due():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    due = db.q("SELECT id FROM posts WHERE status='scheduled' AND scheduled_at <= ? ORDER BY scheduled_at LIMIT 1", (now,))
    for r in due:  # one per minute at most
        publish_post(r["id"])
