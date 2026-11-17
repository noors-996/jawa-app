"""Fake Instagram data so the app can be tried without touching the real account."""
import random


def fake_call(slug, args):
    if slug == "INSTAGRAM_GET_IG_USER_MEDIA":
        return {"data": [
            {"id": "111", "caption": "شوف النظافة ✨🫒", "media_product_type": "REELS",
             "permalink": "https://www.instagram.com/reel/demo1/", "timestamp": "2026-11-16T16:47:41+0000",
             "comments_count": 2},
            {"id": "222", "caption": "اسمع الصوت 🔊🫒", "media_product_type": "REELS",
             "permalink": "https://www.instagram.com/reel/demo2/", "timestamp": "2026-11-15T10:17:29+0000",
             "comments_count": 1},
        ]}
    if slug == "INSTAGRAM_GET_IG_MEDIA_COMMENTS":
        if args["ig_media_id"] == "111":
            return {"data": [
                {"id": "c1", "text": "قديش سعر التنكة؟", "username": "abu_ahmad", "timestamp": "2026-11-16T18:00:00+0000"},
                {"id": "c2", "text": "🔥🔥", "username": "sara", "timestamp": "2026-11-16T18:01:00+0000"},
            ]}
        return {"data": [{"id": "c3", "text": "وين مكانكم بالزبط؟", "username": "omar.k",
                          "timestamp": "2026-11-16T19:00:00+0000"}]}
    if slug == "INSTAGRAM_LIST_ALL_CONVERSATIONS":
        return {"data": [{"id": "conv1", "updated_time": "2026-11-16T20:00:00+0000",
                          "participants": {"data": [{"id": "17841434449825074", "username": "jawapress"},
                                                    {"id": "u55", "username": "rana_nassar"}]}}]}
    if slug == "INSTAGRAM_LIST_ALL_MESSAGES":
        return {"data": [{"id": "m1", "from": {"id": "u55", "username": "rana_nassar"},
                          "message": "مرحبا، قديش العصر للكيلو؟", "created_time": "2026-11-16T20:00:00+0000"}]}
    if slug == "INSTAGRAM_POST_IG_USER_MEDIA":
        return {"id": str(random.randint(10**9, 10**10))}
    if slug == "INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH":
        return {"id": "999"}
    if slug == "INSTAGRAM_GET_IG_MEDIA":
        return {"id": "999", "permalink": "https://www.instagram.com/p/demo-published/"}
    return {"id": "ok"}
