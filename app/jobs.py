"""Background jobs: publish due posts every minute, auto-reply every few hours."""
import json
import threading
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from . import autoreply, db, ig, posts, review

_sched = BackgroundScheduler(timezone="UTC")
_reply_lock = threading.Lock()


def _publish_tick():
    if db.get_settings().get("paused"):
        return
    try:
        posts.publish_due()
    except ig.InstagramStop:
        db.set_settings({"paused": True})


def _last_reply_run():
    r = db.q("SELECT value FROM settings WHERE key='autoreply_last'", one=True)
    return datetime.fromisoformat(json.loads(r["value"])) if r else None


def run_autoreply_now():
    if not _reply_lock.acquire(blocking=False):
        return "شغال هلأ"
    try:
        db.ins("INSERT INTO settings(key,value) VALUES('autoreply_last',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (json.dumps(db.now_iso()),))
        return autoreply.run_once()
    finally:
        _reply_lock.release()


def _autoreply_tick():
    s = db.get_settings()
    if not s["autoreply_enabled"] or s.get("paused") or autoreply._in_quiet_hours(s):
        return
    last = _last_reply_run()
    if last and (datetime.now(timezone.utc) - last).total_seconds() < float(s["autoreply_every_hours"]) * 3600 - 60:
        return
    run_autoreply_now()


def _review_tick():
    try:
        review.check_new_posts()
    except ig.InstagramStop:
        db.set_settings({"paused": True})
        db.add_note("⛔ انستغرام طلب تحقق أو تسجيل دخول. وقّفت كل إشي.")
    except Exception:
        pass  # try again next tick


def start():
    _sched.add_job(_publish_tick, "interval", minutes=1, id="publish", max_instances=1, coalesce=True)
    _sched.add_job(_review_tick, "interval", minutes=10, id="review", max_instances=1, coalesce=True)
    _sched.add_job(_autoreply_tick, "interval", minutes=10, id="autoreply", max_instances=1, coalesce=True)
    _sched.start()
