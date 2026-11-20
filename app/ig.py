"""Instagram access through Composio. Every call goes through call()."""
import json

from . import config

_client = None

STOP_MARKERS = ("oauthexception", "code\": 190", "code=190", "'code': 190", "checkpoint",
                "log in to instagram", "rate limit", "rate-limit", "too many", "code\": 4,", "code\": 17,",
                "code\": 32,", "code\": 613", "session has been invalidated")
WINDOW_MARKERS = ("2534022", "outside of allowed window", "messaging window")


class InstagramStop(Exception):
    """Instagram blocked us (login/checkpoint/rate limit). Stop everything and tell the owner."""


class WindowClosed(Exception):
    """DM can't be sent (24h messaging window closed)."""


class InstagramError(Exception):
    pass


def _get_client():
    global _client
    if _client is None:
        from composio import Composio
        _client = Composio(api_key=config.COMPOSIO_API_KEY)
    return _client


def _as_dict(res):
    if isinstance(res, dict):
        return res
    for attr in ("model_dump", "dict"):
        if hasattr(res, attr):
            return getattr(res, attr)()
    return {"data": res, "successful": True}


_account = None  # (connected_account_id, user_id) found automatically when not set


def _field(obj, name):
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _find_account():
    """Use the newest ACTIVE Instagram connection on this Composio key when no ID is configured."""
    global _account
    if config.COMPOSIO_CONNECTED_ACCOUNT_ID:
        return config.COMPOSIO_CONNECTED_ACCOUNT_ID, config.COMPOSIO_USER_ID
    if _account:
        return _account
    try:
        res = _get_client().connected_accounts.list(
            toolkit_slugs=["instagram"], statuses=["ACTIVE"], order_by="created_at", order_direction="desc")
    except Exception as e:
        _raise_for(str(e))
        raise InstagramError(f"ما قدرت أجيب حسابات انستغرام من Composio: {str(e)[:200]}")
    items = _field(res, "items") or _field(res, "data") or []
    if not items:
        raise InstagramError("ما في حساب انستغرام مربوط وشغال على مفتاح Composio هاد")
    items = sorted(items, key=lambda a: str(_field(a, "created_at") or ""), reverse=True)
    acc = items[0]
    _account = (_field(acc, "id"), _field(acc, "user_id") or config.COMPOSIO_USER_ID)
    return _account


def call(slug: str, arguments: dict) -> dict:
    if config.DEMO_MODE:
        from .demo import fake_call
        return fake_call(slug, arguments)
    account_id, user_id = _find_account()
    kwargs = {"connected_account_id": account_id, "dangerously_skip_version_check": True}
    if user_id:
        kwargs["user_id"] = user_id
    try:
        res = _as_dict(_get_client().tools.execute(slug, arguments, **kwargs))
    except Exception as e:  # network / SDK error
        _raise_for(str(e))
        raise InstagramError(str(e))
    if not res.get("successful", True) or res.get("error"):
        _raise_for(json.dumps(res, ensure_ascii=False))
        raise InstagramError(str(res.get("error") or res)[:500])
    return res.get("data") or {}


def _raise_for(text: str):
    t = text.lower()
    if any(m in t for m in WINDOW_MARKERS):
        raise WindowClosed(text[:300])
    if any(m in t for m in STOP_MARKERS):
        raise InstagramStop(text[:300])


def _items(data):
    d = data.get("data") if isinstance(data, dict) else None
    if isinstance(d, list):
        return d
    if isinstance(d, dict) and isinstance(d.get("data"), list):
        return d["data"]
    return []


# ---------- read ----------
def recent_posts(limit=8, extra_fields=""):
    fields = "id,caption,media_product_type,permalink,timestamp,comments_count,like_count"
    if extra_fields:
        fields += "," + extra_fields
    data = call("INSTAGRAM_GET_IG_USER_MEDIA", {"ig_user_id": "me", "limit": limit, "fields": fields})
    return _items(data)


def comments(media_id, limit=50):
    data = call("INSTAGRAM_GET_IG_MEDIA_COMMENTS", {
        "ig_media_id": media_id, "limit": limit,
        "fields": "id,text,username,timestamp,parent_id,replies{id,text,username,timestamp}"})
    return _items(data)


def conversations(limit=25):
    data = call("INSTAGRAM_LIST_ALL_CONVERSATIONS", {"limit": limit, "fields": "id,updated_time,participants"})
    return _items(data)


def messages(conversation_id, limit=10):
    data = call("INSTAGRAM_LIST_ALL_MESSAGES", {"conversation_id": conversation_id, "limit": limit})
    return _items(data)


# ---------- write ----------
def reply_comment(comment_id, text):
    return call("INSTAGRAM_POST_IG_COMMENT_REPLIES", {"ig_comment_id": comment_id, "message": text})


def send_dm(recipient_id, text):
    return call("INSTAGRAM_SEND_TEXT_MESSAGE", {"recipient_id": recipient_id, "text": text})


def publish(media_url: str, media_type: str, caption: str) -> dict:
    args = {"ig_user_id": config.IG_USER_ID, "caption": caption}
    if media_type in ("REELS", "VIDEO"):
        args.update({"video_url": media_url, "media_type": "REELS", "share_to_feed": True})
    else:
        args["image_url"] = media_url
    container = call("INSTAGRAM_POST_IG_USER_MEDIA", args)
    creation_id = (container.get("id") or (container.get("data") or {}).get("id"))
    if not creation_id:
        raise InstagramError(f"no container id: {container}")
    pub = call("INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH", {
        "ig_user_id": config.IG_USER_ID, "creation_id": str(creation_id), "max_wait_seconds": 240})
    media_id = pub.get("id") or (pub.get("data") or {}).get("id")
    permalink = ""
    if media_id:
        try:
            info = call("INSTAGRAM_GET_IG_MEDIA", {"ig_media_id": str(media_id), "fields": "id,permalink"})
            permalink = info.get("permalink") or (info.get("data") or {}).get("permalink", "")
        except Exception:
            pass
    return {"media_id": media_id, "permalink": permalink}
