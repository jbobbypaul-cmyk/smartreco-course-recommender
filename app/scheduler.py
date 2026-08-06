import logging
import smtplib
from email.message import EmailMessage
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.agent import maybe_generate
from app.config import get_settings
from app.db import SessionLocal
from app.models import Product, Role, User
from app.services import process_vector_outbox

logger = logging.getLogger(__name__)


def _build_digest_message(user: User, reco, products: list[Product], settings) -> EmailMessage:
    lines = [
        f"Hi {user.email},",
        "",
        "Here's your personalized SmartReco learning path based on today's activity:",
        "",
        reco.narrative,
        "",
        "Recommended courses:",
    ]
    html_items = []
    for p in products:
        if not p:
            continue
        lines.append(f"- {p.title} ({p.category}, {p.level}) — ${p.price:.2f}")
        html_items.append(
            f"<li><strong>{p.title}</strong> · {p.category} · {p.level} · ${p.price:.2f}<br>"
            f"<span style='color:#667085'>{p.description[:180]}</span></li>"
        )
    why = ""
    if isinstance(reco.evidence, dict):
        why = reco.evidence.get("why") or ""
    if why:
        lines.extend(["", f"Why this: {why}"])
    lines.extend(["", "Keep exploring — your recommendations adapt as your interests evolve.", "", "— SmartReco"])

    msg = EmailMessage()
    msg["Subject"] = "Your SmartReco learning path"
    msg["From"] = settings.smtp_from
    msg["To"] = user.email
    msg.set_content("\n".join(lines))
    msg.add_alternative(
        f"""
        <html><body style="font-family:system-ui,sans-serif;color:#172033;line-height:1.5">
          <h2>Your SmartReco learning path</h2>
          <p>Hi {user.email},</p>
          <p>{reco.narrative}</p>
          {"<p><em>Why this: " + why + "</em></p>" if why else ""}
          <h3>Recommended courses</h3>
          <ul>{''.join(html_items) or '<li>No active catalog matches yet.</li>'}</ul>
          <p>Keep exploring — recommendations refresh as your behavior changes.</p>
          <p>— SmartReco</p>
        </body></html>
        """,
        subtype="html",
    )
    return msg


def _send_message(msg: EmailMessage, settings) -> None:
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST is not configured")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)


def send_user_digest(db: Session, user: User, force: bool = True) -> dict:
    """Generate (if needed) and email one user's recommendation digest."""
    settings = get_settings()
    reco = maybe_generate(db, user.id, force=force)
    if not reco:
        return {"email": user.email, "status": "skipped", "reason": "no_recommendation"}
    products = [db.get(Product, pid) for pid in (reco.product_ids or [])]
    msg = _build_digest_message(user, reco, products, settings)
    _send_message(msg, settings)
    return {"email": user.email, "status": "sent", "recommendation_id": reco.id}


def daily_digest(force: bool = True) -> dict:
    """Process vector outbox, then email digests to all regular users."""
    settings = get_settings()
    summary = {"sent": 0, "skipped": 0, "failed": 0, "details": []}
    with SessionLocal() as db:
        process_vector_outbox(db)
        if not settings.smtp_host:
            logger.info("SMTP_HOST blank — digest email skipped (outbox still processed)")
            summary["details"].append({"status": "skipped", "reason": "smtp_not_configured"})
            return summary
        users = db.scalars(select(User).where(User.role == Role.user)).all()
        for user in users:
            try:
                result = send_user_digest(db, user, force=force)
                summary["details"].append(result)
                if result["status"] == "sent":
                    summary["sent"] += 1
                else:
                    summary["skipped"] += 1
            except Exception as exc:
                logger.exception("Digest failed for %s", user.email)
                summary["failed"] += 1
                summary["details"].append({"email": user.email, "status": "failed", "error": str(exc)[:300]})
    return summary


def smtp_status() -> dict:
    s = get_settings()
    configured = bool(s.smtp_host and s.smtp_username)
    return {
        "configured": configured,
        "host": s.smtp_host or "",
        "port": s.smtp_port,
        "username": s.smtp_username or "",
        "from": s.smtp_from,
        "use_tls": s.smtp_use_tls,
        "schedule": "daily 15:00 America/Chicago",
    }


def start_scheduler() -> BackgroundScheduler | None:
    if not get_settings().enable_scheduler:
        return None
    scheduler = BackgroundScheduler(timezone="America/Chicago")
    scheduler.add_job(daily_digest, "cron", hour=15, minute=0, id="daily-recommendations", replace_existing=True)
    scheduler.start()
    logger.info("APScheduler started — daily digest at 15:00 America/Chicago")
    return scheduler
