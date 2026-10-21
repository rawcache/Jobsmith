"""Reading your email, read-only, from whichever provider you use.

    gmail    IMAP with a Google app password
    outlook  Microsoft 365 / Outlook (school and work accounts, and outlook.com): sign in with Microsoft once
             (device-code sign-in, no password typed into Jobsmith); IMAP with an OAuth token after that
    imap     any other mail server: host, port, username and password

Only the inbox is opened, always with readonly=True. Tokens and passwords stay in your local settings.

Microsoft sign-in needs an app registration (a client ID). Jobsmith ships none of its own yet: register one for
free in the Azure portal (App registrations > New > "Accounts in any organizational directory and personal
Microsoft accounts", then Authentication > Allow public client flows: Yes, and API permissions > IMAP.AccessAsUser.All
and offline_access) and paste its client ID in Settings. Some schools only allow apps an admin approved; then
Microsoft says so when you sign in, and forwarding your school mail to Gmail is the way around it.
"""
from __future__ import annotations

import imaplib
import time

import httpx

from . import db

MS_SCOPE = "offline_access https://outlook.office.com/IMAP.AccessAsUser.All"
MS_HOST = "outlook.office365.com"
_device: dict = {}                 # the sign-in in progress
_token: dict = {"access": "", "until": 0.0}


def provider(s: dict | None = None) -> str:
    s = s or db.get_settings()
    p = s.get("email_provider") or ""
    if p:
        return p
    addr = (s.get("gmail_address") or "").lower()
    return "outlook" if addr.endswith((".edu", "outlook.com", "hotmail.com", "live.com")) and not s.get("gmail_app_password") else "gmail"


def ready(s: dict | None = None) -> bool:
    s = s or db.get_settings()
    p = provider(s)
    if not s.get("gmail_address"):
        return False
    if p == "gmail":
        return bool(s.get("gmail_app_password"))
    if p == "outlook":
        return bool(s.get("ms_refresh_token") and s.get("ms_client_id"))
    if p == "imap":
        return bool(s.get("imap_host") and s.get("imap_password"))
    return False


def _tenant(s: dict) -> str:
    return s.get("ms_tenant") or "common"


def ms_start() -> dict:
    """Step 1 of Microsoft sign-in: a short code you enter at microsoft.com/devicelogin."""
    s = db.get_settings()
    cid = (s.get("ms_client_id") or "").strip()
    if not cid:
        return {"ok": False, "message": "Add a Microsoft client ID first (see the steps below)."}
    r = httpx.post(f"https://login.microsoftonline.com/{_tenant(s)}/oauth2/v2.0/devicecode",
                   data={"client_id": cid, "scope": MS_SCOPE}, timeout=20)
    d = r.json()
    if r.status_code != 200:
        return {"ok": False, "message": _ms_error(d)}
    _device.clear()
    _device.update(device_code=d["device_code"], interval=int(d.get("interval", 5)), until=time.time() + int(d.get("expires_in", 900)))
    return {"ok": True, "code": d["user_code"], "url": d.get("verification_uri", "https://microsoft.com/devicelogin"),
            "message": "Open the link, enter the code, and sign in with your school or work account."}


def ms_poll() -> dict:
    """Step 2: has the sign-in finished? Saves the refresh token when it has."""
    s = db.get_settings()
    if not _device:
        return {"ok": False, "done": True, "message": "No sign-in in progress. Start again."}
    if time.time() > _device["until"]:
        _device.clear()
        return {"ok": False, "done": True, "message": "The code expired. Start again."}
    r = httpx.post(f"https://login.microsoftonline.com/{_tenant(s)}/oauth2/v2.0/token",
                   data={"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "client_id": s["ms_client_id"],
                         "device_code": _device["device_code"]}, timeout=20)
    d = r.json()
    if r.status_code == 200:
        _device.clear()
        db.set_settings({"ms_refresh_token": d.get("refresh_token", ""), "email_provider": "outlook"})
        _token.update(access=d.get("access_token", ""), until=time.time() + int(d.get("expires_in", 3600)) - 60)
        return {"ok": True, "done": True, "message": "Signed in. Jobsmith can read your inbox (read-only)."}
    if d.get("error") in ("authorization_pending", "slow_down"):
        return {"ok": True, "done": False, "message": "Waiting for you to finish signing in…"}
    _device.clear()
    return {"ok": False, "done": True, "message": _ms_error(d)}


def _ms_error(d: dict) -> str:
    desc = d.get("error_description", "") or d.get("error", "")
    if "AADSTS65001" in desc or "admin" in desc.lower() and "consent" in desc.lower() or "AADSTS90094" in desc:
        return ("Your school or company only allows apps an administrator approved, so Microsoft blocked this sign-in. "
                "Forward your school mail to Gmail (Outlook: Settings > Mail > Forwarding) and connect Gmail instead.")
    if "AADSTS700016" in desc:
        return "Microsoft doesn't recognize that client ID. Copy it again from the Azure portal (Application (client) ID)."
    if "AADSTS7000218" in desc:
        return "Turn on 'Allow public client flows' for the app in the Azure portal (Authentication), then try again."
    return f"Microsoft said: {desc.split(chr(13))[0][:240]}"


def _ms_access(s: dict) -> str:
    if _token["access"] and time.time() < _token["until"]:
        return _token["access"]
    r = httpx.post(f"https://login.microsoftonline.com/{_tenant(s)}/oauth2/v2.0/token",
                   data={"grant_type": "refresh_token", "client_id": s["ms_client_id"], "refresh_token": s["ms_refresh_token"],
                         "scope": MS_SCOPE}, timeout=20)
    d = r.json()
    if r.status_code != 200:
        raise imaplib.IMAP4.error(_ms_error(d))
    if d.get("refresh_token"):
        db.set_settings({"ms_refresh_token": d["refresh_token"]})
    _token.update(access=d["access_token"], until=time.time() + int(d.get("expires_in", 3600)) - 60)
    return _token["access"]


def xoauth2(user: str, token: str) -> bytes:
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode()


def connect(s: dict | None = None) -> imaplib.IMAP4_SSL:
    """A logged-in IMAP connection with the inbox selected read-only. The caller closes it (use `with`)."""
    s = s or db.get_settings()
    p = provider(s)
    addr = s["gmail_address"]
    if p == "outlook":
        m = imaplib.IMAP4_SSL(MS_HOST, 993)
        tok = _ms_access(s)
        m.authenticate("XOAUTH2", lambda _: xoauth2(addr, tok))
    elif p == "imap":
        m = imaplib.IMAP4_SSL(s["imap_host"], int(s.get("imap_port") or 993))
        m.login(s.get("imap_user") or addr, s["imap_password"])
    else:
        m = imaplib.IMAP4_SSL("imap.gmail.com")
        m.login(addr, (s.get("gmail_app_password") or "").replace(" ", ""))
    m.select("INBOX", readonly=True)
    return m
