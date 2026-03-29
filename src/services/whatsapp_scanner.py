"""WhatsApp Web scanner for capturing messages from contacts.

Uses Playwright to automate WhatsApp Web in a persistent browser context,
allowing the operator to scan QR code once and then periodically capture
messages from matched contacts.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional
from src.models.database import get_cursor

logger = logging.getLogger(__name__)

SESSION_DIR = "data/whatsapp_session"


def normalize_phone(raw: str) -> str:
    """Normalize a phone number to digits only with leading +.

    Examples:
        +1 (555) 123-4567 -> +15551234567
        00442071234567 -> +442071234567
        +44 20 7123 4567 -> +442071234567
    """
    if not raw:
        return ""
    digits = re.sub(r"[^\d+]", "", raw)
    # Handle 00 international prefix
    if digits.startswith("00") and not digits.startswith("+"):
        digits = "+" + digits[2:]
    # Ensure leading +
    if not digits.startswith("+"):
        digits = "+" + digits
    return digits


class WhatsAppScanner:
    """Manages WhatsApp Web automation via Playwright."""

    def __init__(self, session_dir: str = SESSION_DIR):
        self.session_dir = session_dir
        self._browser = None
        self._context = None
        self._page = None

    def setup(self) -> str:
        """Launch browser for WhatsApp Web QR code scanning.

        Returns:
            Status message indicating the browser launched.
        """
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=False)
        self._context = self._browser.new_context(
            storage_state=self._get_storage_state(),
        ) if self._has_session() else self._browser.new_context()
        self._page = self._context.new_page()
        self._page.goto("https://web.whatsapp.com")

        return "WhatsApp Web opened. Scan the QR code if prompted."

    def _has_session(self) -> bool:
        """Check if a stored session exists."""
        from pathlib import Path

        return Path(self.session_dir, "state.json").exists()

    def _get_storage_state(self) -> Optional[str]:
        """Get the path to stored browser state."""
        from pathlib import Path

        state_path = Path(self.session_dir, "state.json")
        return str(state_path) if state_path.exists() else None

    def save_session(self) -> None:
        """Save the current browser session for reuse."""
        from pathlib import Path

        Path(self.session_dir).mkdir(parents=True, exist_ok=True)
        if self._context:
            self._context.storage_state(
                path=str(Path(self.session_dir, "state.json"))
            )

    def scan_contacts(self, conn, *, user_id: int) -> dict:
        """Scan WhatsApp for messages from contacts with phone numbers.

        Args:
            conn: PostgreSQL connection

        Returns:
            dict with keys: scanned, new_messages, errors
        """
        with get_cursor(conn) as cur:
            cur.execute(
                """SELECT id, phone_normalized, full_name
                   FROM contacts
                   WHERE phone_normalized IS NOT NULL
                     AND phone_normalized != ''
                     AND user_id = %s""",
                (user_id,),
            )
            contacts = cur.fetchall()

        stats = {"scanned": 0, "new_messages": 0, "errors": 0}

        for contact in contacts:
            try:
                messages = self._extract_messages(contact)
                stats["scanned"] += 1

                for msg in messages:
                    _store_message(
                        conn,
                        contact_id=contact["id"],
                        phone_number=contact["phone_normalized"],
                        message_text=msg["text"],
                        direction=msg["direction"],
                        whatsapp_timestamp=msg.get("timestamp"),
                    )
                    stats["new_messages"] += 1

                # Update scan state
                _update_scan_state(conn, contact["id"])

            except Exception:
                logger.exception(
                    "Error scanning WhatsApp for contact %s", contact["id"]
                )
                stats["errors"] += 1

        conn.commit()
        return stats

    def _extract_messages(self, contact: dict) -> list[dict]:
        """Extract messages from WhatsApp Web for a contact.

        Searches for the contact by phone number, reads visible messages
        from the chat pane.

        Returns:
            List of dicts with keys: text, direction, timestamp
        """
        if not self._page:
            raise RuntimeError("WhatsApp Web not initialized. Call setup() first.")

        phone = contact["phone_normalized"]
        name = contact.get("full_name", phone)

        # Search for contact
        search_box = self._page.locator('[data-testid="chat-list-search"]')
        if not search_box.count():
            search_box = self._page.locator(
                'div[contenteditable="true"][data-tab="3"]'
            )
        if not search_box.count():
            logger.warning("Could not find WhatsApp search box")
            return []

        search_box.first.click()
        search_box.first.fill(phone)
        self._page.wait_for_timeout(2000)

        # Click on the first matching chat
        chat_items = self._page.locator('[data-testid="cell-frame-container"]')
        if not chat_items.count():
            logger.info("No WhatsApp chat found for %s (%s)", name, phone)
            return []

        chat_items.first.click()
        self._page.wait_for_timeout(1000)

        # Read messages from the chat pane
        messages = []
        msg_elements = self._page.locator('[data-testid="msg-container"]')
        count = msg_elements.count()

        for i in range(count):
            el = msg_elements.nth(i)
            try:
                text = el.inner_text()
                is_outbound = "message-out" in (
                    el.evaluate("el => el.className") or ""
                )
                messages.append({
                    "text": text[:2000],
                    "direction": "outbound" if is_outbound else "inbound",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                continue

        return messages

    def close(self) -> None:
        """Save session and close the browser."""
        self.save_session()
        if self._browser:
            self._browser.close()
        if hasattr(self, "_playwright") and self._playwright:
            self._playwright.stop()


def _store_message(
    conn,
    *,
    contact_id: int,
    phone_number: str,
    message_text: str,
    direction: str,
    whatsapp_timestamp: Optional[str] = None,
) -> Optional[int]:
    """Insert a WhatsApp message, ignoring duplicates."""
    with get_cursor(conn) as cur:
        cur.execute(
            """INSERT INTO whatsapp_messages
                   (contact_id, phone_number, message_text, direction, whatsapp_timestamp)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (contact_id, whatsapp_timestamp, direction, message_text)
               DO NOTHING
               RETURNING id""",
            (contact_id, phone_number, message_text, direction, whatsapp_timestamp),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def _update_scan_state(conn, contact_id: int) -> None:
    """Update the scan state for a contact."""
    with get_cursor(conn) as cur:
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """INSERT INTO whatsapp_scan_state (contact_id, last_scanned_at)
               VALUES (%s, %s)
               ON CONFLICT (contact_id)
               DO UPDATE SET last_scanned_at = EXCLUDED.last_scanned_at""",
            (contact_id, now),
        )
