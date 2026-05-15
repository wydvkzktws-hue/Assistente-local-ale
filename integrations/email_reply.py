"""SMTP reply for meeting emails. Reuses Gmail app-password from email_config.json."""

import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

from integrations.email_sync import load_config

DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587

TEMPLATES = {
    "en": {
        "attending": "Hi,\n\nI'll be attending the meeting.\n\nThanks,",
        "decline":   "Hi,\n\nUnfortunately I won't be able to attend the meeting.\n\nThanks,",
        "tentative": "Hi,\n\nI'm tentative for the meeting — I'll confirm as soon as possible.\n\nThanks,",
    },
    "pt": {
        "attending": "Olá,\n\nConfirmo minha presença na reunião.\n\nObrigado,",
        "decline":   "Olá,\n\nInfelizmente não poderei participar da reunião.\n\nObrigado,",
        "tentative": "Olá,\n\nAinda não tenho certeza se poderei participar — confirmarei o mais breve possível.\n\nObrigado,",
    },
}


def build_body(language: str, choice: str, custom: str | None = None) -> str:
    if custom:
        return custom
    lang = TEMPLATES.get(language, TEMPLATES["en"])
    return lang.get(choice, lang["attending"])


def send_reply(
    to_addr: str,
    subject: str,
    in_reply_to_msgid: str | None,
    body: str,
    smtp_host: str = DEFAULT_SMTP_HOST,
    smtp_port: int = DEFAULT_SMTP_PORT,
) -> dict:
    cfg = load_config()
    if not cfg:
        return {"ok": False, "error": "not_configured"}

    from_addr = cfg["email"]
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = from_addr
    msg["To"] = to_addr
    re_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg["Subject"] = re_subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    if in_reply_to_msgid:
        msg["In-Reply-To"] = in_reply_to_msgid
        msg["References"] = in_reply_to_msgid

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as s:
            s.starttls()
            s.login(cfg["email"], cfg["app_password"])
            s.sendmail(from_addr, [to_addr], msg.as_string())
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
