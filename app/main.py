import hashlib
import hmac
import json
import threading
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import agent, config, db, jobs, posts

STATIC = Path(__file__).parent.parent / "static"
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/media", StaticFiles(directory=config.MEDIA_DIR), name="media")  # public: Instagram fetches from here
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------- login ----------
def _token():
    return hmac.new(config.SECRET_KEY.encode(), config.APP_PASSWORD.encode(), hashlib.sha256).hexdigest()


def auth(request: Request):
    if not config.APP_PASSWORD:
        return
    if not hmac.compare_digest(request.cookies.get("t", ""), _token()):
        raise HTTPException(401, "سجل دخول")


@app.post("/api/login")
async def login(request: Request, response: Response):
    body = await request.json()
    if not hmac.compare_digest(body.get("password", ""), config.APP_PASSWORD):
        raise HTTPException(401, "كلمة السر غلط")
    response.set_cookie("t", _token(), max_age=60 * 60 * 24 * 90, httponly=True, samesite="lax",
                        secure=config.PUBLIC_BASE_URL.startswith("https"))
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/manifest.json")
def manifest():
    return JSONResponse({
        "name": config.APP_NAME, "short_name": config.APP_NAME, "start_url": "/", "display": "standalone",
        "dir": "rtl", "lang": "ar", "background_color": "#f6f3ea", "theme_color": "#3d5a2a",
        "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}]})


@app.get("/sw.js")
def sw():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript")


@app.get("/api/me", dependencies=[Depends(auth)])
def me():
    return {"app_name": config.APP_NAME, "demo": config.DEMO_MODE, "paused": db.get_settings().get("paused"),
            "unseen": len(db.q("SELECT id FROM notes WHERE seen=0"))}


# ---------- uploads ----------
def _save_upload(f: UploadFile) -> str:
    raw = f.file.read()
    name = (f.filename or "").lower()
    if name.endswith(posts.VIDEO_EXT) or (f.content_type or "").startswith("video"):
        fn = f"{uuid.uuid4().hex}.mp4"
        (config.MEDIA_DIR / fn).write_bytes(raw)
        return fn
    from io import BytesIO
    from PIL import Image, ImageOps
    try:
        img = ImageOps.exif_transpose(Image.open(BytesIO(raw))).convert("RGB")
    except Exception:
        raise HTTPException(400, "الملف مش صورة أو فيديو مدعوم (استعمل JPG/PNG أو MP4)")
    img.thumbnail((1440, 1800))
    fn = f"{uuid.uuid4().hex}.jpg"
    img.save(config.MEDIA_DIR / fn, "JPEG", quality=90)
    return fn


@app.post("/api/upload", dependencies=[Depends(auth)])
def upload(file: UploadFile = File(...)):
    fn = _save_upload(file)
    return {"file": fn, "type": posts.media_type_for(fn), "url": f"/media/{fn}"}


# ---------- chat ----------
@app.get("/api/messages", dependencies=[Depends(auth)])
def history():
    out = []
    for r in db.q("SELECT id, role, content FROM messages ORDER BY id DESC LIMIT 80")[::-1]:
        c = json.loads(r["content"])
        if isinstance(c, str):
            out.append({"role": r["role"], "text": c})
        else:
            t = "".join(b.get("text", "") for b in c if b.get("type") == "text")
            if t.strip():
                out.append({"role": r["role"], "text": t})
    pending = db.q("SELECT id, kind, summary, status, result FROM actions WHERE status='pending' ORDER BY id")
    return {"messages": out, "pending": pending}


@app.post("/api/chat", dependencies=[Depends(auth)])
def chat(text: str = Form(""), file: UploadFile | None = File(None)):
    fn = _save_upload(file) if file and file.filename else None
    if not text.strip() and not fn:
        raise HTTPException(400, "اكتب إشي")
    try:
        return agent.chat(text.strip() or "شوف هالملف", fn)
    except Exception as e:
        raise HTTPException(500, f"صار خطأ: {str(e)[:200]}")


@app.post("/api/chat/reset", dependencies=[Depends(auth)])
def chat_reset():
    db.q("DELETE FROM messages")
    return {"ok": True}


@app.post("/api/actions/{aid}/approve", dependencies=[Depends(auth)])
def approve(aid: int):
    return {"result": agent.execute_action(aid)}


@app.post("/api/actions/{aid}/reject", dependencies=[Depends(auth)])
def reject(aid: int):
    db.q("UPDATE actions SET status='rejected' WHERE id=? AND status='pending'", (aid,))
    return {"ok": True}


# ---------- schedule ----------
@app.get("/api/posts", dependencies=[Depends(auth)])
def list_posts():
    return {"posts": posts.listing(), "next_slot": posts.to_local_str(posts.next_free_slot().isoformat())}


@app.post("/api/posts", dependencies=[Depends(auth)])
def create_post(media_file: str = Form(...), caption: str = Form(...), when_local: str = Form("")):
    try:
        return posts.schedule(Path(media_file).name, caption, when_local or None)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/posts/{pid}", dependencies=[Depends(auth)])
async def edit_post(pid: int, request: Request):
    b = await request.json()
    try:
        return posts.update(pid, b.get("caption"), b.get("when_local") or None)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/posts/{pid}", dependencies=[Depends(auth)])
def cancel_post(pid: int):
    posts.cancel(pid)
    return {"ok": True}


@app.post("/api/posts/{pid}/publish", dependencies=[Depends(auth)])
def publish_now(pid: int):
    if db.get_settings().get("paused"):
        raise HTTPException(400, "الحساب موقف مؤقتاً. شغله من الإعدادات.")
    try:
        posts.publish_post(pid)
    except Exception:
        db.set_settings({"paused": True})
    return posts.view(db.q("SELECT * FROM posts WHERE id=?", (pid,), one=True))


@app.post("/api/caption", dependencies=[Depends(auth)])
async def caption(request: Request):
    b = await request.json()
    fn = Path(b.get("media_file", "")).name
    note = b.get("note", "")
    msg = f"اكتبلي كابشن واحد بس لهالبوست، بدون أي كلام زيادة قبله أو بعده. فكرة البوست: {note or 'من الصورة'}"
    import anthropic, base64
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    content = [{"type": "text", "text": msg}]
    if fn and posts.media_type_for(fn) == "IMAGE" and (config.MEDIA_DIR / fn).exists():
        data = base64.standard_b64encode((config.MEDIA_DIR / fn).read_bytes()).decode()
        content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
    resp = client.messages.create(model=config.MODEL, max_tokens=800, system=agent.SYSTEM,
                                  messages=[{"role": "user", "content": content}])
    return {"caption": "".join(x.text for x in resp.content if x.type == "text").strip()}


# ---------- settings & notes ----------
@app.get("/api/settings", dependencies=[Depends(auth)])
def get_settings():
    return db.get_settings()


@app.post("/api/settings", dependencies=[Depends(auth)])
async def save_settings(request: Request):
    b = await request.json()
    if "autoreply_max_replies" in b:
        b["autoreply_max_replies"] = max(0, min(4, int(b["autoreply_max_replies"])))
    return db.set_settings(b)


@app.get("/api/notes", dependencies=[Depends(auth)])
def notes():
    rows = db.q("SELECT * FROM notes ORDER BY id DESC LIMIT 50")
    for r in rows:
        r["created_local"] = posts.to_local_str(r["created"])
    return {"notes": rows}


@app.post("/api/notes/seen", dependencies=[Depends(auth)])
def notes_seen():
    db.q("UPDATE notes SET seen=1")
    return {"ok": True}


@app.post("/api/autoreply/run", dependencies=[Depends(auth)])
def autoreply_run():
    threading.Thread(target=jobs.run_autoreply_now, daemon=True).start()
    return {"ok": True}


@app.on_event("startup")
def _start():
    jobs.start()
