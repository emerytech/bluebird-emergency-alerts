from __future__ import annotations

import email as email_lib
import email.header
import imaplib
import logging
import re
import uuid
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Optional

import anyio

from app.services.email_service import EmailService

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[^\w@.\-]+")


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "\n".join(p.strip() for p in self._parts if p.strip())


def _strip_html(html: str) -> str:
    s = _HTMLStripper()
    try:
        s.feed(html)
        return s.get_text()
    except Exception:
        return html


def _decode_header_value(raw: str) -> str:
    parts = email.header.decode_header(raw or "")
    out: list[str] = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                out.append(part.decode(charset or "utf-8", errors="replace"))
            except Exception:
                out.append(part.decode("utf-8", errors="replace"))
        else:
            out.append(str(part))
    return "".join(out).strip()


def _extract_body(msg: email_lib.message.Message) -> tuple[str, str]:
    """Return (text_body, html_body) from a parsed email message."""
    text_body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition") or "")
            if "attachment" in cd:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                decoded = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if ct == "text/plain" and not text_body:
                text_body = decoded
            elif ct == "text/html" and not html_body:
                html_body = decoded
    else:
        ct = msg.get_content_type()
        charset = msg.get_content_charset() or "utf-8"
        try:
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes):
                decoded = payload.decode(charset, errors="replace")
                if ct == "text/html":
                    html_body = decoded
                else:
                    text_body = decoded
        except Exception:
            pass
    if html_body and not text_body:
        text_body = _strip_html(html_body)
    return text_body.strip(), html_body.strip()


class InboxSyncService:
    """
    Fetches unread emails via IMAP and stores them in the email_messages table.
    Completely isolated from emergency alert delivery — touches only platform.db.
    """

    def __init__(self, email_service: EmailService) -> None:
        self._es = email_service

    def _sync_inbox_sync(self) -> int:
        """Fetch unseen messages from IMAP and store new ones. Returns count of new messages."""
        creds = self._es.get_imap_credentials_sync()
        if not creds["username"] or not creds["password"]:
            logger.debug("InboxSync: IMAP credentials not configured, skipping.")
            return 0

        host = creds["host"] or "imap.gmail.com"
        port = int(creds["port"] or 993)
        username = creds["username"]
        password = creds["password"]

        new_count = 0
        try:
            with imaplib.IMAP4_SSL(host, port) as imap:
                imap.login(username, password)
                imap.select("INBOX", readonly=False)
                # Search for ALL messages, not just UNSEEN, to handle manual reads
                _status, data = imap.search(None, "UNSEEN")
                if _status != "OK" or not data or not data[0]:
                    return 0
                uids = data[0].split()
                # Process newest first, cap at 50 per sync cycle
                for uid_bytes in reversed(uids[-50:]):
                    uid = uid_bytes.decode()
                    try:
                        new_count += self._process_message(imap, uid)
                    except Exception:
                        logger.exception("InboxSync: error processing UID %s", uid)
        except imaplib.IMAP4.error as exc:
            logger.warning("InboxSync: IMAP error — %s", exc)
        except Exception:
            logger.exception("InboxSync: unexpected error during sync")
        return new_count

    def _process_message(self, imap: imaplib.IMAP4_SSL, uid: str) -> int:
        """Fetch a single message, store it if new. Returns 1 if stored, 0 if skipped."""
        _st, msg_data = imap.fetch(uid, "(RFC822)")
        if _st != "OK" or not msg_data or msg_data[0] is None:
            return 0

        raw = msg_data[0][1]
        if not isinstance(raw, bytes):
            return 0

        msg = email_lib.message_from_bytes(raw)

        # Use the Message-ID header as dedup key; fall back to a derived UID key
        message_id_header = _decode_header_value(msg.get("Message-ID") or "").strip("<> ")
        if not message_id_header:
            message_id_header = f"uid-{uid}-{uuid.uuid4().hex[:8]}"

        if self._es.message_id_exists_sync(message_id_header):
            return 0

        subject = _decode_header_value(msg.get("Subject") or "")
        from_raw = _decode_header_value(msg.get("From") or "")
        from_name, from_email = parseaddr(from_raw)
        to_raw = _decode_header_value(msg.get("To") or "")
        _, to_email = parseaddr(to_raw)
        thread_id = _decode_header_value(msg.get("References") or msg.get("In-Reply-To") or "").split()[0] if msg.get("References") or msg.get("In-Reply-To") else None

        # Parse date
        date_str = msg.get("Date")
        received_at: Optional[str] = None
        if date_str:
            try:
                received_at = parsedate_to_datetime(date_str).isoformat()
            except Exception:
                received_at = datetime.now(timezone.utc).isoformat()

        text_body, html_body = _extract_body(msg)

        stored = self._es.store_message_sync(
            provider_message_id=message_id_header,
            thread_id=thread_id,
            direction="inbound",
            from_email=from_email.lower().strip(),
            from_name=from_name.strip(),
            to_email=to_email.lower().strip(),
            subject=subject,
            body_text=text_body,
            body_html=html_body,
            received_at=received_at,
            sent_at=None,
            is_read=False,
            status="new",
        )
        return 1 if stored else 0

    async def sync_inbox(self) -> int:
        return await anyio.to_thread.run_sync(self._sync_inbox_sync)
