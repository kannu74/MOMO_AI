"""Email outbox: Momo can only WRITE emails. Sending needs you to press Approve in the window.

    voice -> draft_email tool -> create_draft()   recipient checked against EMAIL_CONTACTS (egress control),
                                                  stored as 'pending', the window is told to show it
    window: you read To / Subject / Body -> [Approve & send] (mouse click, optional PIN) -> approve()
                                                  re-checks everything, then sends over SMTP (TLS)

Why voice can't approve: there is no tool for it, and approve() needs the secret the window got from
register_approver() when it started. The LLM, tools and the voice loop never see that secret. approve() also
gets the hash of exactly what the window displayed, so a draft can't be swapped after you read it.
Nothing in Momo sends email on a schedule; drafts expire after EMAIL_DRAFT_TTL_MIN minutes.
"""
import hashlib
import hmac
import secrets
import smtplib
import ssl
import threading
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import config
from backend.database import connect, now

from .audit import log_event
from .egress import recipient_allowed, resolve_recipient

_approver_secret = None
_notify = None                 # window callback: called with a draft dict when a new one needs approval
_lock = threading.Lock()


def register_approver(notify) -> str:
    """Called once by the window. Returns the secret approve() requires."""
    global _approver_secret, _notify
    with _lock:
        if _approver_secret is not None:
            raise RuntimeError("an approver is already registered")
        _approver_secret, _notify = secrets.token_hex(32), notify
    with connect() as conn:                 # drafts from an earlier run were never shown in this window
        conn.execute("UPDATE email_outbox SET status='expired', decided_at=? WHERE status='pending'", (now(),))
    return _approver_secret


def has_approver() -> bool:
    return _approver_secret is not None


def content_hash(d: dict) -> str:
    return hashlib.sha256("\x1f".join((d["id"], d["to_addr"], d["subject"], d["body"])).encode()).hexdigest()


def _expire_old(conn):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=config.EMAIL_DRAFT_TTL_MIN)).isoformat(timespec="seconds")
    conn.execute("UPDATE email_outbox SET status='expired', decided_at=? WHERE status='pending' AND created_at < ?",
                 (now(), cutoff))


def pending() -> list[dict]:
    with connect() as conn:
        _expire_old(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM email_outbox WHERE status='pending' ORDER BY created_at")]


def create_draft(to: str, subject: str, body: str, tainted: bool = False) -> str:
    """Returns a sentence for Momo to say."""
    T = config.USER_TITLE
    if not config.EMAIL_CONTACTS:
        return (f"Email isn't set up yet, {T}. Add EMAIL_CONTACTS and your SMTP details to the .env file, "
                "then I can write emails for you to approve.")
    who = resolve_recipient(to)
    if not who:
        log_event("email_blocked", f"recipient not in contacts: {to[:80]!r}")
        names = ", ".join(sorted(config.EMAIL_CONTACTS))
        return f"I can't email {to or 'that person'}, {T}. I can only write to your approved contacts: {names}."
    subject = " ".join((subject or "A message from Momo").split())[:150]
    body = (body or "").strip()[:4000]
    if not body:
        return f"What should the email to {who[0]} say, {T}?"
    d = {"id": secrets.token_hex(8), "to_name": who[0], "to_addr": who[1], "subject": subject, "body": body,
         "tainted": int(bool(tainted)), "status": "pending", "created_at": now()}
    with connect() as conn:
        conn.execute("INSERT INTO email_outbox (id, to_name, to_addr, subject, body, tainted, status, created_at) "
                     "VALUES (:id, :to_name, :to_addr, :subject, :body, :tainted, :status, :created_at)", d)
    log_event("email_drafted", f"{d['id']} to {who[0]} <{who[1]}> subject={subject!r} tainted={bool(tainted)}")
    if _notify:
        _notify(d)
        return f"I've written the email to {who[0]}, {T}. Please read it and press Approve on my screen to send it."
    return f"I've written the email to {who[0]}, {T}, but it can only be sent from my window. Please open it to approve."


def _get(draft_id):
    with connect() as conn:
        _expire_old(conn)
        r = conn.execute("SELECT * FROM email_outbox WHERE id=?", (draft_id,)).fetchone()
    return dict(r) if r else None


def _decide(draft_id, status, note=""):
    with connect() as conn:
        conn.execute("UPDATE email_outbox SET status=?, decided_at=?, note=? WHERE id=?", (status, now(), note, draft_id))


def cancel_pending() -> int:
    """Discard every waiting draft. Allowed by voice: it can only ever stop an email, never send one."""
    with connect() as conn:
        n = conn.execute("UPDATE email_outbox SET status='rejected', decided_at=?, note='cancelled by voice' "
                         "WHERE status='pending'", (now(),)).rowcount
    if n:
        log_event("email_rejected", f"{n} draft(s) cancelled by voice")
    return n


def status(draft_id: str) -> str:
    d = _get(draft_id)
    return d["status"] if d else "gone"


def reject(draft_id: str, secret: str) -> str:
    if not (_approver_secret and hmac.compare_digest(secret or "", _approver_secret)):
        log_event("email_reject_refused", draft_id)
        return "Not allowed."
    _decide(draft_id, "rejected")
    log_event("email_rejected", draft_id)
    return "Email discarded."


def approve(draft_id: str, secret: str, shown_hash: str, pin: str = "") -> tuple[bool, str]:
    """Send an approved draft. Only the window can call this successfully."""
    if not (_approver_secret and hmac.compare_digest(secret or "", _approver_secret)):
        log_event("email_approve_refused", f"{draft_id}: wrong approver secret")
        return False, "Approval refused: it didn't come from the Momo window."
    if config.EMAIL_APPROVAL_PIN and not hmac.compare_digest(pin or "", config.EMAIL_APPROVAL_PIN):
        log_event("email_approve_refused", f"{draft_id}: wrong PIN")
        return False, "Wrong PIN. The email was not sent."
    d = _get(draft_id)
    if not d or d["status"] != "pending":
        return False, f"This draft is {d['status'] if d else 'gone'}; nothing was sent."
    if not hmac.compare_digest(shown_hash or "", content_hash(d)):
        log_event("email_approve_refused", f"{draft_id}: content changed after it was shown")
        _decide(draft_id, "failed", "content changed after display")
        return False, "The draft changed after you saw it, so it was not sent."
    if not recipient_allowed(d["to_addr"]):                     # egress control, checked again at send time
        log_event("email_blocked", f"{draft_id}: {d['to_addr']} is not an approved contact")
        _decide(draft_id, "failed", "recipient not allowed")
        return False, "That address isn't one of your approved contacts. Not sent."
    if config.SMTP_HOST not in config.ALLOWED_HOSTS:
        _decide(draft_id, "failed", "smtp host not allowed")
        return False, "The mail server isn't on the allowlist. Not sent."
    if not (config.SMTP_USER and config.SMTP_PASSWORD and config.EMAIL_FROM):
        return False, "Email isn't set up: add SMTP_USER and SMTP_PASSWORD (an app password) to .env."

    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.EMAIL_FROM, d["to_addr"], d["subject"]
    msg.set_content(d["body"])
    try:
        ctx = ssl.create_default_context()
        if config.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=ctx, timeout=20) as s:
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.send_message(msg, to_addrs=[d["to_addr"]])
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.send_message(msg, to_addrs=[d["to_addr"]])
    except Exception as e:
        log_event("email_failed", f"{draft_id}: {type(e).__name__}")
        _decide(draft_id, "failed", type(e).__name__)
        return False, f"Sending failed ({type(e).__name__}). Check the SMTP settings in .env."
    _decide(draft_id, "sent")
    log_event("email_sent", f"{draft_id} to {d['to_name']} <{d['to_addr']}>")
    return True, f"Email to {d['to_name']} sent."
