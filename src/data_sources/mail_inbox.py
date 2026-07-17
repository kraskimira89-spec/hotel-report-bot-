"""Чтение входящей почты по IMAP (Issue #13)."""

from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import re
from datetime import date, datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any

from pydantic import BaseModel

from src.config import (
    AppConfig,
    ImapMailboxConfig,
    MailInboxConfig,
    get_config,
    get_env_settings,
)
from src.data_sources.mail_report_parsers import (
    ParsedServiceReport,
    parse_service_report,
)

logger = logging.getLogger(__name__)

MailClass = str  # inquiry | review | service_report | other


class MailMessage(BaseModel):
    """Нормализованное письмо."""

    message_id: str
    mailbox: str
    folder: str
    from_addr: str = ""
    subject: str = ""
    received_at: datetime | None = None
    body_text: str = ""
    mail_class: MailClass = "other"
    for_reviews: bool = False
    parsed_report: ParsedServiceReport | None = None
    headers_hash: str = ""


def _decode_mime(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001
        return value


def _body_from_message(msg: Message, limit: int = 8000) -> str:
    parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.casefold():
                continue
            if ctype == "text/plain":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                try:
                    parts.append(payload.decode(charset, errors="replace"))
                except Exception:  # noqa: BLE001
                    parts.append(payload.decode("utf-8", errors="replace"))
            elif ctype == "text/html" and not parts:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                html = payload.decode(charset, errors="replace")
                text = re.sub(r"<[^>]+>", " ", html)
                parts.append(re.sub(r"\s+", " ", text).strip())
    else:
        payload = msg.get_payload(decode=True) or b""
        charset = msg.get_content_charset() or "utf-8"
        try:
            parts.append(payload.decode(charset, errors="replace"))
        except Exception:  # noqa: BLE001
            parts.append(payload.decode("utf-8", errors="replace"))
    text = "\n".join(parts).strip()
    return text[:limit]


def _message_id_of(msg: Message, mailbox: str, folder: str, uid: str) -> str:
    mid = (msg.get("Message-ID") or msg.get("Message-Id") or "").strip()
    if mid:
        return mid
    raw = f"{mailbox}|{folder}|{uid}|{msg.get('Subject')}|{msg.get('Date')}"
    return "gen-" + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:32]


def classify_mail(
    from_addr: str,
    subject: str,
    body: str,
    report_senders: list[str],
) -> tuple[MailClass, bool]:
    """Правила: service_report / review / inquiry / other (+ for_reviews)."""
    from_l = (from_addr or "").casefold()
    subj_l = (subject or "").casefold()
    body_l = (body or "").casefold()[:2000]
    blob = f"{subj_l}\n{body_l}"

    for sender in report_senders:
        s = (sender or "").casefold().strip()
        if not s:
            continue
        if s.startswith("@") and s in from_l:
            return "service_report", False
        if s and s in from_l:
            return "service_report", False

    review_kw = (
        "отзыв",
        "review",
        "оценка проживания",
        "оставил отзыв",
        "рейтинг",
    )
    if any(k in blob for k in review_kw):
        return "review", True

    inquiry_kw = (
        "обращение",
        "жалоба",
        "претензи",
        "бронирован",
        "запрос",
        "вопрос по",
        "не заселили",
        "возврат",
    )
    if any(k in blob for k in inquiry_kw):
        return "inquiry", True

    if "travelline" in from_l or "отчёт" in subj_l or "отчет" in subj_l:
        return "service_report", False

    return "other", False


def _credentials_for(account: str) -> tuple[str, str]:
    env = get_env_settings()
    if account == "gmail":
        return (env.imap_gmail_user or "").strip(), (env.imap_gmail_password or "").strip()
    return (env.imap_yandex_user or "").strip(), (env.imap_yandex_password or "").strip()


def _imap_since(period_start: date) -> str:
    # IMAP SINCE — английский месяц
    months = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )
    return f"{period_start.day:02d}-{months[period_start.month - 1]}-{period_start.year}"


def _fetch_folder(
    client: imaplib.IMAP4,
    mailbox_cfg: ImapMailboxConfig,
    folder: str,
    period_start: date,
    period_end: date,
    report_senders: list[str],
) -> list[MailMessage]:
    typ, _ = client.select(folder, readonly=True)
    if typ != "OK":
        logger.warning("IMAP: не удалось открыть папку %s", folder)
        return []

    since = _imap_since(period_start)
    typ, data = client.search(None, "SINCE", since)
    if typ != "OK" or not data or not data[0]:
        return []

    results: list[MailMessage] = []
    for uid in data[0].split():
        typ, msg_data = client.fetch(uid, "(RFC822)")
        if typ != "OK" or not msg_data or not msg_data[0]:
            continue
        raw = msg_data[0][1]
        if not isinstance(raw, (bytes, bytearray)):
            continue
        msg = email.message_from_bytes(raw)
        subject = _decode_mime(msg.get("Subject"))
        from_addr = _decode_mime(msg.get("From"))
        body = _body_from_message(msg)
        received: datetime | None = None
        try:
            if msg.get("Date"):
                received = parsedate_to_datetime(msg.get("Date"))
                if received.tzinfo is None:
                    received = received.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            received = None
        if received is not None:
            rd = received.date()
            if rd < period_start or rd > period_end:
                continue

        mail_class, for_reviews = classify_mail(
            from_addr, subject, body, report_senders
        )
        parsed = None
        if mail_class == "service_report":
            parsed = parse_service_report(subject, body, from_addr)

        mid = _message_id_of(msg, mailbox_cfg.account, folder, uid.decode())
        headers_hash = hashlib.sha256(
            f"{from_addr}|{subject}|{msg.get('Date')}".encode("utf-8", errors="replace")
        ).hexdigest()[:40]

        results.append(
            MailMessage(
                message_id=mid,
                mailbox=mailbox_cfg.account,
                folder=folder,
                from_addr=from_addr,
                subject=subject,
                received_at=received,
                body_text=body,
                mail_class=mail_class,
                for_reviews=for_reviews,
                parsed_report=parsed,
                headers_hash=headers_hash,
            )
        )
    return results


def fetch_mailbox(
    mailbox_cfg: ImapMailboxConfig,
    period_start: date,
    period_end: date,
    report_senders: list[str],
) -> list[MailMessage]:
    """Скачать письма одного ящика за период."""
    if not mailbox_cfg.enabled:
        return []
    user, password = _credentials_for(mailbox_cfg.account)
    if not user or not password:
        logger.info(
            "IMAP %s: нет учётных данных — пропуск",
            mailbox_cfg.account,
        )
        return []
    host = mailbox_cfg.host or (
        "imap.gmail.com" if mailbox_cfg.account == "gmail" else "imap.yandex.ru"
    )
    port = mailbox_cfg.port or 993
    try:
        if mailbox_cfg.use_ssl:
            client: imaplib.IMAP4 = imaplib.IMAP4_SSL(host, port)
        else:
            client = imaplib.IMAP4(host, port)
        client.login(user, password)
    except Exception as exc:  # noqa: BLE001
        logger.warning("IMAP %s недоступен: %s", mailbox_cfg.account, exc)
        return []

    out: list[MailMessage] = []
    try:
        for folder in mailbox_cfg.folders or ["INBOX"]:
            try:
                out.extend(
                    _fetch_folder(
                        client,
                        mailbox_cfg,
                        folder,
                        period_start,
                        period_end,
                        report_senders,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "IMAP %s/%s: %s",
                    mailbox_cfg.account,
                    folder,
                    exc,
                )
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass
    return out


def fetch_messages(
    period_start: date | None = None,
    period_end: date | None = None,
    *,
    config: AppConfig | None = None,
) -> list[MailMessage]:
    """Собрать письма со всех включённых ящиков."""
    cfg = config or get_config()
    inbox: MailInboxConfig = cfg.mail_inbox
    if not inbox.enabled:
        logger.info("mail_inbox выключен в settings — пропуск")
        return []

    period_end = period_end or date.today()
    period_start = period_start or (
        period_end - timedelta(days=max(1, inbox.lookback_days))
    )

    messages: list[MailMessage] = []
    for box in inbox.mailboxes:
        messages.extend(
            fetch_mailbox(box, period_start, period_end, inbox.report_senders)
        )
    logger.info(
        "mail_inbox: собрано %s писем за %s…%s",
        len(messages),
        period_start,
        period_end,
    )
    return messages


def collect_and_save_mail_inbox(
    period_start: date | None = None,
    period_end: date | None = None,
) -> int:
    """Fetch + сохранить в SQLite. Возвращает число сохранённых строк."""
    from src.storage.db import save_mail_messages
    from src.storage.models import MailMessageRecord

    msgs = fetch_messages(period_start, period_end)
    records: list[MailMessageRecord] = []
    for m in msgs:
        parsed_json: dict[str, Any] = {}
        if m.parsed_report is not None:
            parsed_json = m.parsed_report.model_dump()
        records.append(
            MailMessageRecord(
                message_id=m.message_id,
                mailbox=m.mailbox,
                folder=m.folder,
                from_addr=m.from_addr,
                subject=m.subject,
                received_at=m.received_at,
                body_excerpt=(m.body_text or "")[:2000],
                mail_class=m.mail_class,
                for_reviews=m.for_reviews,
                parsed_json=parsed_json,
                headers_hash=m.headers_hash,
            )
        )
    return save_mail_messages(records)
