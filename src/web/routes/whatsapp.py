"""WhatsApp integration API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(tags=["whatsapp"])


@router.post("/whatsapp/setup")
@_limiter.limit("3/minute")
def whatsapp_setup(request: Request, conn=Depends(get_db), user=Depends(get_current_user)):
    """Start a WhatsApp Web session for QR code scanning."""
    try:
        from src.services.whatsapp_scanner import WhatsAppScanner

        scanner = WhatsAppScanner()
        message = scanner.setup()
        return {"status": "ok", "message": message}
    except ImportError:
        raise HTTPException(
            400,
            "Playwright not installed. Run: pip install playwright && playwright install chromium",
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to start WhatsApp session: {e}")


@router.post("/whatsapp/scan")
@_limiter.limit("2/minute")
def whatsapp_scan(request: Request, conn=Depends(get_db), user=Depends(get_current_user)):
    """Trigger a WhatsApp message scan for all contacts with phone numbers."""
    try:
        from src.services.whatsapp_scanner import WhatsAppScanner

        scanner = WhatsAppScanner()
        scanner.setup()
        result = scanner.scan_contacts(conn)
        scanner.close()
        return {"status": "ok", **result}
    except ImportError:
        raise HTTPException(
            400,
            "Playwright not installed. Run: pip install playwright && playwright install chromium",
        )
    except Exception as e:
        raise HTTPException(500, f"WhatsApp scan failed: {e}")


@router.get("/whatsapp/scan/status")
def whatsapp_scan_status(conn=Depends(get_db), user=Depends(get_current_user)):
    """Get the last scan time and message counts."""
    with get_cursor(conn) as cur:
        # Last scan time
        cur.execute(
            "SELECT MAX(last_scanned_at) AS last_scan FROM whatsapp_scan_state"
        )
        row = cur.fetchone()
        last_scan = row["last_scan"] if row else None

        # Total message count (scoped to current user's contacts)
        cur.execute(
            "SELECT COUNT(*) AS count FROM whatsapp_messages WHERE contact_id IN (SELECT id FROM contacts WHERE user_id = %s)",
            (user["id"],),
        )
        msg_count = cur.fetchone()["count"]

        # Contacts with messages (scoped to current user's contacts)
        cur.execute(
            "SELECT COUNT(DISTINCT contact_id) AS count FROM whatsapp_messages WHERE contact_id IN (SELECT id FROM contacts WHERE user_id = %s)",
            (user["id"],),
        )
        contacts_with_messages = cur.fetchone()["count"]

        return {
            "last_scan": last_scan,
            "total_messages": msg_count,
            "contacts_with_messages": contacts_with_messages,
        }


@router.get("/whatsapp/messages")
def whatsapp_messages(
    contact_id: int = Query(...),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get WhatsApp messages for a specific contact."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT wm.*, c.full_name AS contact_name
               FROM whatsapp_messages wm
               JOIN contacts c ON c.id = wm.contact_id
               JOIN companies co ON co.id = c.company_id
               WHERE wm.contact_id = %s AND co.user_id = %s
               ORDER BY wm.whatsapp_timestamp DESC, wm.captured_at DESC""",
            (contact_id, user["id"]),
        )
        return [dict(r) for r in cur.fetchall()]
