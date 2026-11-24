from __future__ import annotations
import asyncio
import os, json, secrets
from dotenv import load_dotenv

load_dotenv()
from datetime import datetime, timezone
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import settings, STATIC_DIR
from app.database import Base, SessionLocal, engine, init_db
from app.database.models import Post
from app.security import require_admin
from app.oauth_state import COOKIE_NAME, COOKIE_MAX_AGE_SECONDS, issue_state_cookie, verify_state_cookie

APP_NAME = settings.APP_NAME

init_db()
from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(application: FastAPI):
    from app.scheduler import start_scheduler, stop_scheduler

    await start_scheduler()
    try:
        yield
    finally:
        await stop_scheduler()


app = FastAPI(title=APP_NAME, version=settings.APP_VERSION, lifespan=_lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

class GenerateRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    category: str = "Crypto Discussion"
    tone: str = "natural crypto native"
    language: str = "ru"
    structure: list[str] = Field(default_factory=list)
    examples: list[dict] = Field(default_factory=list)
    cta: str | None = None
    style_limits: str | None = None
    post_format: str | None = None

class EditRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)

@app.get("/")
def home(_: HTTPBasicCredentials = Depends(require_admin)):
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/api/health")
def health(_: HTTPBasicCredentials = Depends(require_admin)):
    return {
        "ok": True,
        "app": APP_NAME,
        "version": settings.APP_VERSION,
        "ai_configured": bool(settings.gemini_api_key or settings.openrouter_api_key),
        "threads_configured": bool(settings.threads_access_token),
        "content_library_configured": bool(settings.content_library_token),
        "research_enabled": True,
    }

@app.get("/healthz")
def liveness():
    # No admin auth, and no secret/configuration details.
    return {"ok": True}

# Public, static Meta App Review pages. These routes never use HTTP Basic
# and do not expose private drafts, account data or environment variables.
PUBLIC_META_PAGES = {
    "/meta": "meta-meta.html",
    "/privacy": "meta-privacy.html",
    "/terms": "meta-terms.html",
    "/data-deletion": "meta-data-deletion.html",
}


@app.get("/meta", include_in_schema=False)
@app.get("/privacy", include_in_schema=False)
@app.get("/terms", include_in_schema=False)
@app.get("/data-deletion", include_in_schema=False)
def meta_public_page(request: Request):
    filename = PUBLIC_META_PAGES[request.url.path]
    return FileResponse(
        STATIC_DIR / filename,
        media_type="text/html; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Cache-Control": "public, max-age=3600",
        },
    )


@app.get("/robots.txt", include_in_schema=False)
def meta_robots_txt():
    return FileResponse(STATIC_DIR / "robots.txt", media_type="text/plain; charset=utf-8")


@app.get("/research")
def research_page(_: HTTPBasicCredentials = Depends(require_admin)):
    return FileResponse(STATIC_DIR / "research.html")


@app.get("/auth/threads/start", include_in_schema=False)
def threads_oauth_start(_: HTTPBasicCredentials = Depends(require_admin)):
    """Start Meta OAuth on Render. No manual state copying is needed."""
    from tools.refresh_threads_token import auth_url

    state = secrets.token_urlsafe(32)
    try:
        cookie = issue_state_cookie(state)
        target_url = auth_url(state_override=state)
    except (SystemExit, ValueError) as exc:
        # Configuration errors contain variable names, never secret values.
        raise HTTPException(status_code=503, detail=str(exc)) from None
    response = RedirectResponse(target_url, status_code=302)
    response.set_cookie(
        COOKIE_NAME, cookie, max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True, secure=True, samesite="lax", path="/auth/threads",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/auth/threads/callback", include_in_schema=False)
def threads_oauth_callback(request: Request, code: str | None = None, error: str | None = None):
    """OAuth callback: check browser-bound state and show Meta's one-time code."""
    import html as _html

    # Never log auth codes, query parameters or OAuth secrets.
    supplied_state = request.query_params.get("state", "")
    state_cookie = request.cookies.get(COOKIE_NAME, "")
    if state_cookie:
        valid_state = verify_state_cookie(state_cookie, supplied_state)
    else:
        # Backward compatible with v0.3.2 local CLI-generated authorization URLs.
        # New users should always visit /auth/threads/start instead.
        expected_state = os.getenv("THREADS_OAUTH_STATE", "").strip()
        valid_state = bool(expected_state and supplied_state and secrets.compare_digest(supplied_state, expected_state))

    if not valid_state:
        body = (
            "<h2>OAuth state не совпадает</h2>"
            "<p>Не открывайте /auth/threads/callback вручную. "
            "Авторизацию нужно начать в той же вкладке браузера через "
            "<a style='color:#70b7ff' href='/auth/threads/start'>Подключить Threads</a>. "
            "Если прошло больше 10 минут, повторите вход. "
            "Проверьте адрес THREADS_REDIRECT_URI в Render и Meta.</p>"
        )
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'><body style='font:15px system-ui;"
            f"background:#0b1020;color:#edf3ff;padding:32px'>{body}</body>",
            status_code=400,
            headers={"Cache-Control": "no-store"},
        )

    if error or not code:
        body = (
            "<h2>Авторизация не завершена</h2>"
            f"<p>error: {_html.escape(error or 'Отсутствует code')}</p>"
        )
    else:
        body = (
            "<h2>Код получен</h2><p>Скопируйте его и выполните на своём ПК:</p>"
            "<pre>python tools/refresh_threads_token.py exchange &quot;&lt;CODE&gt;&quot;</pre>"
            f"<textarea readonly rows='4' style='width:100%'>{_html.escape(code)}</textarea>"
            "<p>Это одноразовый код. Не отправляйте его в чат и не публикуйте.</p>"
        )
    response = HTMLResponse(
        "<!doctype html><meta charset='utf-8'><body style='font:15px system-ui;"
        f"background:#0b1020;color:#edf3ff;padding:32px'>{body}</body>",
        headers={"Cache-Control": "no-store"},
    )
    response.delete_cookie(COOKIE_NAME, path="/auth/threads", secure=True, httponly=True, samesite="lax")
    return response

def serialize(p: Post):
    return {"id": p.id, "text": p.text, "category": p.category,
            "language": getattr(p, "language", "ru") or "ru", "status": p.status,
            "campaign_id": p.campaign_id, "hook_type": p.hook_type,
            "goal": p.goal, "offer_id": p.offer_id, "editorial_score": p.editorial_score,
            "tracking_url": p.tracking_url,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "published_at": p.published_at.isoformat() if p.published_at else None,
            "threads_post_id": p.threads_post_id}

@app.get("/api/posts")
def list_posts(_: HTTPBasicCredentials = Depends(require_admin)):
    with SessionLocal() as db:
        rows = db.query(Post).order_by(Post.created_at.desc()).limit(100).all()
        return [serialize(p) for p in rows]

@app.post("/api/generate")
async def generate(req: GenerateRequest, _: HTTPBasicCredentials = Depends(require_admin)):
    from app.writer_service import generate_text

    text = await generate_text(
        topic=req.topic,
        category=req.category,
        tone=req.tone,
        language=req.language,
        structure=req.structure,
        examples=req.examples,
        cta=req.cta,
        style_limits=req.style_limits,
        post_format=req.post_format,
    )
    if len(text) > 500:
        raise HTTPException(502, "AI выдал текст длиннее 500 символов; повтори генерацию")
    with SessionLocal() as db:
        post = Post(
            text=text,
            category=req.category,
            language=(req.language or "ru")[:20],
            status="pending_review",
        )
        db.add(post); db.commit(); db.refresh(post)
        return serialize(post)

@app.patch("/api/posts/{post_id}")
def edit_post(post_id: int, req: EditRequest, _: HTTPBasicCredentials = Depends(require_admin)):
    with SessionLocal() as db:
        p = db.get(Post, post_id)
        if not p: raise HTTPException(404, "Post not found")
        if p.status in {"published", "publishing", "publish_uncertain"}: raise HTTPException(409, "Публикация заблокирована")
        p.text = req.text.strip(); p.status = "pending_review"; db.commit(); db.refresh(p)
        return serialize(p)

@app.post("/api/posts/{post_id}/approve")
def approve_post(post_id: int, _: HTTPBasicCredentials = Depends(require_admin)):
    with SessionLocal() as db:
        p = db.get(Post, post_id)
        if not p: raise HTTPException(404, "Post not found")
        if p.status in {"published", "publishing", "publish_uncertain"}: raise HTTPException(409, "Публикация заблокирована")
        p.status = "approved"; db.commit(); db.refresh(p)
        return serialize(p)

@app.post("/api/posts/{post_id}/reject")
def reject_post(post_id: int, _: HTTPBasicCredentials = Depends(require_admin)):
    with SessionLocal() as db:
        p = db.get(Post, post_id)
        if not p: raise HTTPException(404, "Post not found")
        if p.status in {"published", "publishing", "publish_uncertain"}: raise HTTPException(409, "Публикация заблокирована")
        p.status = "rejected"; db.commit(); db.refresh(p)
        return serialize(p)

@app.post("/api/posts/{post_id}/publish")
async def publish_post(post_id: int, _: HTTPBasicCredentials = Depends(require_admin)):
    from app.publishing_queue import publish_claimed
    await publish_claimed(post_id)
    with SessionLocal() as db:
        return serialize(db.get(Post, post_id))


@app.post("/api/posts/{post_id}/reset-publish", dependencies=[Depends(require_admin)])
def reset_uncertain_post(post_id: int):
    """Manual reset ONLY after checking Threads for a possibly published duplicate."""
    with SessionLocal() as db:
        p = db.get(Post, post_id)
        if not p: raise HTTPException(404, "Post not found")
        if p.status != "publish_uncertain":
            raise HTTPException(409, "Статус публикации не требует сброса")
        p.status = "pending_review"
        db.commit(); db.refresh(p)
        return serialize(p)


# --- Research Engine extension (new module, Writer routes above untouched) ---
from app.api import research_router

app.include_router(research_router)
from app.api.growth import router as growth_router, redirect_router
app.include_router(growth_router)
from app.api.style_lab import router as style_lab_router
app.include_router(style_lab_router)
app.include_router(redirect_router)

