"""Routes every bot site has: landing/pricing, Discord login, dashboard, billing, Stripe webhook, admin."""
import asyncio
import logging
import secrets
from datetime import timedelta
from urllib.parse import quote

import stripe
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import billing, discord_api, entitlements, registry
from ..config import settings
from ..models import AuditLog, BillingCustomer, Guild, Subscription, WebSession, utcnow
from .deps import (STATE_COOKIE, SESSION_COOKIE, audit, back, check_csrf, get_db, get_session, guild_ctx, render,
                   require_admin, require_user)

log = logging.getLogger("utilbots.web")
SESSION_DAYS = 7
router = APIRouter()


@router.get("/healthz")
async def healthz():
    return {"ok": True, "bot": registry.spec().slug}


# ---- public ---------------------------------------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def index(request: Request, ws: WebSession | None = Depends(get_session)):
    return render(request, "index.html", ws, invite=discord_api.invite_url())


@router.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request, ws: WebSession | None = Depends(get_session)):
    return render(request, "pricing.html", ws, invite=discord_api.invite_url())


@router.get("/terms")
async def terms():
    return RedirectResponse(f"{settings.legal_base_url}/terms")


@router.get("/privacy")
async def privacy():
    return RedirectResponse(f"{settings.legal_base_url}/privacy")


# ---- Discord login --------------------------------------------------------------------------------------------
@router.get("/login")
async def login(next: str = "/dashboard"):
    if not settings.discord_client_id:
        raise HTTPException(503, "Discord OAuth is not configured (DISCORD_CLIENT_ID).")
    state = secrets.token_urlsafe(16)
    resp = RedirectResponse(discord_api.login_url(state))
    nxt = next if next.startswith("/") and not next.startswith("//") else "/dashboard"
    resp.set_cookie(STATE_COOKIE, f"{state}|{nxt}", max_age=600, httponly=True, samesite="lax",
                    secure=settings.public_url.startswith("https"))
    return resp


@router.get("/auth/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None,
                   db: Session = Depends(get_db)):
    saved, _, nxt = request.cookies.get(STATE_COOKIE, "").partition("|")
    if not code or not state or not saved or not secrets.compare_digest(saved, state):
        return back("/", err="Login failed, please try again.")
    try:
        token = await discord_api.exchange_code(code)
        me, guilds = await discord_api.fetch_identity(token)
    except Exception:
        log.exception("discord oauth failed")
        return back("/", err="Discord login failed.")
    ws = WebSession(token=discord_api.new_token(), csrf=secrets.token_urlsafe(24), user_id=int(me["id"]),
                    username=me.get("global_name") or me["username"], avatar=me.get("avatar"), guilds=guilds,
                    expires_at=utcnow() + timedelta(days=SESSION_DAYS))
    db.add(ws)
    db.commit()
    resp = RedirectResponse(nxt or "/dashboard", status_code=303)
    resp.set_cookie(SESSION_COOKIE, ws.token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                    secure=settings.public_url.startswith("https"))
    resp.delete_cookie(STATE_COOKIE)
    return resp


@router.post("/logout")
async def logout(csrf: str = Form(""), ws: WebSession = Depends(require_user), db: Session = Depends(get_db)):
    check_csrf(ws, csrf)
    db.delete(ws)
    db.commit()
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ---- dashboard ------------------------------------------------------------------------------------------------
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, ws: WebSession = Depends(require_user), db: Session = Depends(get_db)):
    ids = [int(g["id"]) for g in ws.guilds]
    rows = {g.id: g for g in db.scalars(select(Guild).where(Guild.id.in_(ids)))} if ids else {}
    items = [{"g": g, "installed": bool(rows.get(int(g["id"])) and rows[int(g["id"])].installed),
              "plan": entitlements.effective_plan(db, int(g["id"])),
              "invite": discord_api.invite_url(int(g["id"]))} for g in ws.guilds]
    items.sort(key=lambda i: (not i["installed"], i["g"]["name"].lower()))
    return render(request, "dashboard.html", ws, items=items)


@router.get("/guild/{guild_id}", response_class=HTMLResponse)
async def guild_page(guild_id: int, request: Request, ws: WebSession = Depends(require_user),
                     db: Session = Depends(get_db)):
    """Default settings page; bots with settings register their own /guild/{id} route first."""
    guild = await guild_ctx(db, ws, guild_id)
    return render(request, "guild.html", ws, guild=guild, plan=entitlements.effective_plan(db, guild_id))


# ---- billing --------------------------------------------------------------------------------------------------
@router.get("/guild/{guild_id}/billing", response_class=HTMLResponse)
async def billing_page(guild_id: int, request: Request, ws: WebSession = Depends(require_user),
                       db: Session = Depends(get_db)):
    guild = await guild_ctx(db, ws, guild_id)
    plan = entitlements.effective_plan(db, guild_id)
    return render(request, "billing.html", ws, guild=guild, plan=plan,
                  expiry=entitlements.current_expiry(db, guild_id),
                  can_trial=settings.trial_enabled and not guild.trial_used and plan.rank == 0,
                  trial_plan=registry.plans().get(registry.spec().trial_plan),
                  stripe_on=billing.configured(db), has_customer=db.get(BillingCustomer, guild_id) is not None)


@router.post("/guild/{guild_id}/billing/trial")
async def start_trial(guild_id: int, ws: WebSession = Depends(require_user), db: Session = Depends(get_db),
                      csrf: str = Form("")):
    check_csrf(ws, csrf)
    guild = await guild_ctx(db, ws, guild_id)
    if not settings.trial_enabled or not entitlements.start_trial(db, guild, settings.trial_days):
        return back(f"/guild/{guild_id}/billing", err="A trial isn't available for this server.")
    audit(db, ws.user_id, "trial.start", str(guild_id))
    db.commit()
    name = registry.plans().get(registry.spec().trial_plan).name
    return back(f"/guild/{guild_id}/billing", msg=f"{name} trial started for {settings.trial_days} days")


@router.post("/guild/{guild_id}/billing/checkout")
async def checkout(guild_id: int, ws: WebSession = Depends(require_user), db: Session = Depends(get_db),
                   csrf: str = Form(""), plan: str = Form(...)):
    check_csrf(ws, csrf)
    await guild_ctx(db, ws, guild_id)
    url = f"/guild/{guild_id}/billing"
    if not billing.configured(db):
        return back(url, err="Online payment isn't enabled yet. Contact the bot owner to upgrade.")
    customer = db.get(BillingCustomer, guild_id)
    live_stripe = [s for s in db.scalars(select(Subscription).where(
        Subscription.guild_id == guild_id, Subscription.source == "stripe")) if s.is_live()]
    if live_stripe:  # plan changes go through the portal so we never create a second paid subscription
        return back(url, err="This server already has a subscription. Use Manage billing to change it.")
    try:
        target = await asyncio.to_thread(billing.create_checkout, guild_id, plan,
                                         customer.customer_id if customer else None)
    except ValueError as exc:
        return back(url, err=str(exc))
    except stripe.StripeError as exc:
        log.error("checkout failed (%s): %s", type(exc).__name__, exc)
        if isinstance(exc, stripe.AuthenticationError):
            msg = "Payments are misconfigured. Please contact the bot owner."
        elif isinstance(exc, stripe.APIConnectionError):
            msg = "Couldn't reach the payment provider. Please try again in a moment."
        else:
            msg = "Couldn't start checkout. Please try again later."
        return back(url, err=msg)
    return RedirectResponse(target, status_code=303)


@router.post("/guild/{guild_id}/billing/portal")
async def portal(guild_id: int, ws: WebSession = Depends(require_user), db: Session = Depends(get_db),
                 csrf: str = Form("")):
    check_csrf(ws, csrf)
    await guild_ctx(db, ws, guild_id)
    customer = db.get(BillingCustomer, guild_id)
    if not billing.configured(db) or not customer:
        return back(f"/guild/{guild_id}/billing", err="No billing account found for this server.")
    try:
        target = await asyncio.to_thread(billing.create_portal, db, guild_id, customer.customer_id)
    except stripe.StripeError as exc:
        log.warning("portal failed: %s", exc)
        return back(f"/guild/{guild_id}/billing", err="Couldn't open the billing portal. Please try again later.")
    return RedirectResponse(target, status_code=303)


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    if not billing.webhook_secret(db):
        raise HTTPException(503, "Stripe is not configured")
    try:
        event = billing.parse_event(db, await request.body(), request.headers.get("stripe-signature", ""))
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Invalid webhook")
    if event["type"] in billing.EVENTS:
        obj = event["data"]["object"]
        if billing.apply_subscription(db, obj):
            audit(db, None, "stripe." + event["type"].rsplit(".", 1)[1],
                  (obj.get("metadata") or {}).get("guild_id", ""), f"{obj.get('id')} status={obj.get('status')}")
        db.commit()
    return {"received": True}


# ---- site admin -----------------------------------------------------------------------------------------------
@router.get("/admin", response_class=HTMLResponse)
async def admin_home(request: Request, ws: WebSession = Depends(require_admin), db: Session = Depends(get_db)):
    plans = registry.plans()
    now = utcnow()
    live = [s for s in db.scalars(select(Subscription).where(Subscription.status == "active")) if s.is_live(now)]
    best: dict[int, str] = {}
    for sub in live:
        p = plans.get(sub.plan)
        if p and (sub.guild_id not in best or p.rank > plans.get(best[sub.guild_id]).rank):
            best[sub.guild_id] = sub.plan
    by_plan = {p.key: sum(1 for v in best.values() if v == p.key) for p in plans.paid}
    stats = [("installed servers", db.scalar(select(func.count()).select_from(Guild).where(Guild.installed.is_(True))))]
    stats += [(f"{plans.get(k).name} servers", v) for k, v in by_plan.items()]
    hook = getattr(request.app.state, "admin_stats", None)
    if hook:
        stats += list(hook(db))
    return render(request, "admin_home.html", ws, stats=stats)


@router.get("/admin/guilds", response_class=HTMLResponse)
async def admin_guilds(request: Request, q: str = "", ws: WebSession = Depends(require_admin),
                       db: Session = Depends(get_db)):
    stmt = select(Guild).order_by(Guild.installed.desc(), Guild.name).limit(200)
    term = q.strip()
    if term:
        cond = Guild.name.ilike(f"%{term}%")
        stmt = stmt.where(cond | (Guild.id == int(term)) if term.isdigit() else cond)
    guilds = db.scalars(stmt).all()
    return render(request, "admin_guilds.html", ws, guilds=guilds, q=q,
                  plans={g.id: entitlements.effective_plan(db, g.id) for g in guilds})


@router.get("/admin/guilds/{guild_id}", response_class=HTMLResponse)
async def admin_guild(guild_id: int, request: Request, ws: WebSession = Depends(require_admin),
                      db: Session = Depends(get_db)):
    guild = db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(404)
    return render(request, "admin_guild.html", ws, guild=guild, plan=entitlements.effective_plan(db, guild_id),
                  now=utcnow())


@router.post("/admin/guilds/{guild_id}/grant")
async def admin_grant(guild_id: int, ws: WebSession = Depends(require_admin), db: Session = Depends(get_db),
                      csrf: str = Form(""), plan: str = Form(...), days: str = Form(""), note: str = Form("")):
    check_csrf(ws, csrf)
    if not db.get(Guild, guild_id):
        raise HTTPException(404)
    try:
        entitlements.grant(db, guild_id, plan, days=int(days) if days.isdigit() and int(days) > 0 else None,
                           note=note[:255], granted_by=ws.user_id)
    except ValueError as exc:
        return back(f"/admin/guilds/{guild_id}", err=str(exc))
    audit(db, ws.user_id, "sub.grant", str(guild_id), f"{plan} days={days or 'forever'} {note}")
    db.commit()
    return back(f"/admin/guilds/{guild_id}", msg="Subscription granted")


@router.post("/admin/guilds/{guild_id}/revoke")
async def admin_revoke(guild_id: int, ws: WebSession = Depends(require_admin), db: Session = Depends(get_db),
                       csrf: str = Form("")):
    check_csrf(ws, csrf)
    n = entitlements.revoke(db, guild_id)
    audit(db, ws.user_id, "sub.revoke", str(guild_id), f"{n} canceled")
    db.commit()
    return back(f"/admin/guilds/{guild_id}", msg=f"Canceled {n} subscription(s)")


@router.post("/admin/guilds/{guild_id}/toggle")
async def admin_toggle(guild_id: int, ws: WebSession = Depends(require_admin), db: Session = Depends(get_db),
                       csrf: str = Form("")):
    check_csrf(ws, csrf)
    guild = db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(404)
    guild.disabled = not guild.disabled
    audit(db, ws.user_id, "guild.disable" if guild.disabled else "guild.enable", str(guild_id))
    db.commit()
    return back(f"/admin/guilds/{guild_id}", msg="Server disabled" if guild.disabled else "Server enabled")


@router.get("/admin/audit", response_class=HTMLResponse)
async def admin_audit(request: Request, ws: WebSession = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200)).all()
    return render(request, "admin_audit.html", ws, rows=rows)


def login_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)
