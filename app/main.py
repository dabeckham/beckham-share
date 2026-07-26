"""Beckham Share — FastAPI application and HTTP routes.

Access tiers
------------
* Public landing page (``/``)        — anyone; offers a constrained anonymous upload.
* Public share pages (``/s/{uuid}``) — anyone with the link, until it expires.
* Authenticated app (``/app``)       — OIDC (Authentik) + ``dropbox`` group only.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import fingerprint, ratelimit, storage
from .auth import clear_user, get_current_user, oauth, store_user
from .config import settings
from .db import get_db, init_db
from .emailer import EmailNotConfigured, send_share_email
from .models import File as FileModel
from .models import ShareLink, UploadEvent, utcnow

log = logging.getLogger("beckham_share")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.ensure_dirs()
    init_db()
    log.info("%s started (oidc_configured=%s, email_enabled=%s)",
             settings.app_name, settings.oidc_configured, settings.email_enabled)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    https_only=True,
    same_site="lax",
    max_age=60 * 60 * 12,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def expiry_label(hours: int) -> str:
    if hours == 0:
        return "Never expires"
    if hours < 24:
        return f"{hours} hour" + ("s" if hours != 1 else "")
    days = hours // 24
    return f"{days} day" + ("s" if days != 1 else "")


templates.env.globals["expiry_label"] = expiry_label


# ── helpers ──────────────────────────────────────────────────────────────
def share_url(token: str) -> str:
    return f"{settings.base_url.rstrip('/')}/s/{token}"


# The app is reachable on several hostnames, but share links and the OIDC
# session cookie are tied to one canonical host (BASE_URL). Auth routes redirect
# there so the login state/cookie stays consistent across the flow.
CANONICAL_HOST = urlsplit(settings.base_url).hostname


def ensure_canonical_host(request: Request):
    host = request.url.hostname
    if CANONICAL_HOST and host and host != CANONICAL_HOST:
        return RedirectResponse(
            url=str(request.url.replace(netloc=CANONICAL_HOST, scheme="https")),
            status_code=302,
        )
    return None


def expiry_from_hours(hours: int) -> "object | None":
    return None if hours == 0 else utcnow() + timedelta(hours=hours)


def base_context(request: Request) -> dict:
    user = get_current_user(request)
    return {
        "settings": settings,
        "user": user,
        "expiry_options": settings.expiry_options,
        "default_expiry": settings.default_share_expiry_hours,
    }


def render(request: Request, template: str, extra: dict | None = None, status_code: int = 200):
    """Render a template with the shared base context merged in."""
    return templates.TemplateResponse(
        request, template, {**base_context(request), **(extra or {})}, status_code=status_code,
    )


def error_page(request: Request, code: int, message: str):
    return render(request, "error.html", {"code": code, "message": message}, status_code=code)


def record_event(db: Session, request: Request, file: FileModel, *, anonymous: bool,
                 user=None, client_fp: str | None = None, fp_data=None) -> UploadEvent:
    info = fingerprint.collect(request, client_fp, fp_data)
    event = UploadEvent(
        file_id=file.id,
        is_anonymous=anonymous,
        actor_sub=getattr(user, "sub", None),
        actor_email=getattr(user, "email", None),
        **info,
    )
    db.add(event)
    return event


def humanize_size(n: int) -> str:
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < step:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= step
    return f"{n:.1f} PB"


# ── public: landing + health ───────────────────────────────────────────────
@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/app", status_code=302)
    return render(request, "landing.html")


@app.post("/api/anon-upload")
async def anon_upload(
    request: Request,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    fp: str | None = Form(None),
    fp_data: str | None = Form(None),
):
    ip = fingerprint.client_ip(request)
    client_fp = fp
    fingerprint_hash = fingerprint.compute_fingerprint(request, client_fp, ip)
    try:
        ratelimit.check_anonymous(db, ip, fingerprint_hash)
    except ratelimit.RateLimited as exc:
        return JSONResponse({"ok": False, "error": exc.message}, status_code=429,
                            headers={"Retry-After": str(exc.retry_after_seconds)})

    record = FileModel(
        original_filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        is_anonymous=True,
        expires_at=expiry_from_hours(settings.anon_share_expiry_hours),
    )
    db.add(record)
    db.flush()  # assign record.id

    try:
        size, sha = await storage.save_upload(file, record.id, settings.anon_max_upload_bytes)
    except storage.UploadTooLarge as exc:
        db.rollback()
        return JSONResponse(
            {"ok": False, "error": f"File too large. Anonymous uploads are limited to {humanize_size(exc.limit)}."},
            status_code=413,
        )
    record.size_bytes, record.sha256 = size, sha

    link = ShareLink(file_id=record.id, expires_at=record.expires_at)
    db.add(link)
    record_event(db, request, record, anonymous=True, client_fp=client_fp,
                 fp_data=_parse_json(fp_data))
    db.commit()

    log.info("anon upload id=%s ip=%s fp=%s size=%s name=%r",
             record.id, ip, fingerprint_hash[:12], size, record.original_filename)
    return {
        "ok": True,
        "token": link.token,
        "share_url": share_url(link.token),
        "filename": record.original_filename,
        "size": size,
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
    }


# ── auth ────────────────────────────────────────────────────────────────────
@app.get("/login")
async def login(request: Request):
    redirect = ensure_canonical_host(request)
    if redirect:
        return redirect
    if not settings.oidc_configured:
        raise HTTPException(503, "Sign-in is not configured yet.")
    redirect_uri = f"{settings.base_url.rstrip('/')}/auth/callback"
    return await oauth.authentik.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    try:
        token = await oauth.authentik.authorize_access_token(request)
    except Exception as exc:  # noqa: BLE001 - surface a friendly error page
        log.warning("OIDC callback failed: %s", exc)
        return error_page(request, 400, "Sign-in failed. Please try again.")
    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo = await oauth.authentik.userinfo(token=token)
    store_user(request, dict(userinfo))
    return RedirectResponse(url="/app", status_code=302)


@app.get("/logout")
def logout(request: Request):
    clear_user(request)
    return RedirectResponse(url="/", status_code=302)


# ── authenticated interface ────────────────────────────────────────────────
def require_member(request: Request):
    """Return the current member, or ``None`` (caller decides how to respond)."""
    user = get_current_user(request)
    if user and user.in_required_group:
        return user
    return user  # may be None or a non-member; routes differentiate


@app.get("/app", response_class=HTMLResponse)
def app_home(request: Request, db: Session = Depends(get_db)):
    redirect = ensure_canonical_host(request)
    if redirect:
        return redirect
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not user.in_required_group:
        return render(request, "not_authorized.html", status_code=403)
    files = db.execute(
        select(FileModel)
        .where(FileModel.owner_sub == user.sub, FileModel.deleted.is_(False))
        .order_by(FileModel.created_at.desc())
    ).scalars().all()
    rows = [_file_row(f) for f in files]
    return render(request, "app.html", {"files": rows, "usage": humanize_size(storage.disk_usage_bytes())})


@app.post("/api/files")
async def upload_file(
    request: Request,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    expiry_hours: int = Form(settings.default_share_expiry_hours),
    fp: str | None = Form(None),
    fp_data: str | None = Form(None),
):
    user = get_current_user(request)
    if not user or not user.in_required_group:
        raise HTTPException(403, "Not authorized.")
    if expiry_hours not in settings.expiry_options:
        expiry_hours = settings.default_share_expiry_hours

    record = FileModel(
        original_filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        owner_sub=user.sub,
        owner_email=user.email,
        is_anonymous=False,
    )
    db.add(record)
    db.flush()
    try:
        size, sha = await storage.save_upload(file, record.id, settings.max_upload_bytes)
    except storage.UploadTooLarge as exc:
        db.rollback()
        return JSONResponse(
            {"ok": False, "error": f"File too large (limit {humanize_size(exc.limit)})."},
            status_code=413,
        )
    record.size_bytes, record.sha256 = size, sha

    link = ShareLink(file_id=record.id, created_by_sub=user.sub, expires_at=expiry_from_hours(expiry_hours))
    db.add(link)
    record_event(db, request, record, anonymous=False, user=user, client_fp=fp, fp_data=_parse_json(fp_data))
    db.commit()
    return {"ok": True, **_file_row(record)}


@app.post("/api/shares/{token}/expiry")
def update_expiry(token: str, request: Request, expiry_hours: int = Form(...), db: Session = Depends(get_db)):
    user = get_current_user(request)
    link = _owned_link(db, token, user)
    if expiry_hours not in settings.expiry_options:
        raise HTTPException(400, "Invalid expiry option.")
    link.expires_at = expiry_from_hours(expiry_hours)
    link.revoked = False
    db.commit()
    return {"ok": True, "token": token, "expires_at": link.expires_at.isoformat() if link.expires_at else None}


@app.post("/api/shares/{token}/revoke")
def revoke_share(token: str, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    link = _owned_link(db, token, user)
    link.revoked = True
    db.commit()
    return {"ok": True}


@app.delete("/api/files/{file_id}")
def delete_file(file_id: str, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user or not user.in_required_group:
        raise HTTPException(403, "Not authorized.")
    record = db.get(FileModel, file_id)
    if not record or record.owner_sub != user.sub:
        raise HTTPException(404, "Not found.")
    record.deleted = True
    storage.delete_blob(record.id)
    db.commit()
    return {"ok": True}


@app.post("/api/shares/{token}/email")
def email_share(token: str, request: Request, to: str = Form(...), db: Session = Depends(get_db)):
    link = db.get(ShareLink, token)
    if not link or link.is_expired:
        raise HTTPException(404, "Link not found or expired.")
    # Server-side relay is restricted to signed-in members so the public share
    # page can't be used as a spam relay; anonymous visitors use a mailto: link.
    user = get_current_user(request)
    if not user or not user.in_required_group:
        raise HTTPException(403, "Server-side email is for signed-in members.")
    sender = getattr(user, "name", None)
    try:
        send_share_email(to, share_url(token), link.file.original_filename, sender)
    except EmailNotConfigured:
        return JSONResponse({"ok": False, "reason": "email_not_configured"}, status_code=503)
    except Exception as exc:  # noqa: BLE001
        log.warning("email send failed: %s", exc)
        return JSONResponse({"ok": False, "reason": "send_failed"}, status_code=502)
    return {"ok": True}


# ── public share + download ─────────────────────────────────────────────────
@app.get("/s/{token}", response_class=HTMLResponse)
def share_page(token: str, request: Request, db: Session = Depends(get_db)):
    link = db.get(ShareLink, token)
    if not link or link.file.deleted:
        return error_page(request, 404, "This link doesn't exist.")
    if link.is_expired:
        return error_page(request, 410, "This link has expired.")
    return render(request, "share.html", {
        "file": link.file,
        "size_h": humanize_size(link.file.size_bytes),
        "token": token,
        "download_url": f"{settings.base_url.rstrip('/')}/d/{token}",
        "this_url": share_url(token),
        "expires_at": link.expires_at,
    })


@app.get("/d/{token}")
def download(token: str, db: Session = Depends(get_db)):
    link = db.get(ShareLink, token)
    if not link or link.file.deleted:
        raise HTTPException(404, "Not found.")
    if link.is_expired:
        raise HTTPException(410, "This link has expired.")
    path = storage.blob_path(link.file.id)
    if not path:
        raise HTTPException(404, "File is no longer available.")
    link.download_count += 1
    db.commit()
    return FileResponse(
        path,
        media_type=link.file.content_type,
        filename=link.file.original_filename,  # restores the real name on save only
    )


# ── small internal helpers ──────────────────────────────────────────────────
def _parse_json(raw: str | None):
    import json
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _owned_link(db: Session, token: str, user) -> ShareLink:
    if not user or not user.in_required_group:
        raise HTTPException(403, "Not authorized.")
    link = db.get(ShareLink, token)
    if not link or link.file.owner_sub != user.sub:
        raise HTTPException(404, "Not found.")
    return link


def _file_row(f: FileModel) -> dict:
    link = f.shares[0] if f.shares else None
    return {
        "id": f.id,
        "filename": f.original_filename,
        "size": f.size_bytes,
        "size_h": humanize_size(f.size_bytes),
        "content_type": f.content_type,
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "token": link.token if link else None,
        "share_url": share_url(link.token) if link else None,
        "expires_at": link.expires_at.isoformat() if link and link.expires_at else None,
        "revoked": link.revoked if link else False,
        "downloads": link.download_count if link else 0,
    }
