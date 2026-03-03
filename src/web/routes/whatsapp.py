"""WhatsApp integration API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.web.dependencies import get_db

router = APIRouter(tags=["whatsapp"])


@router.post("/whatsapp/setup")
def whatsapp_setup(conn=Depends(get_db)):
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
def whatsapp_scan(conn=Depends(get_db)):
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
def whatsapp_scan_status(conn=Depends(get_db)):
    """Get the last scan time and message counts."""
    cur = conn.cursor()

    # Last scan time
    cur.execute(
        "SELECT MAX(last_scanned_at) AS last_scan FROM whatsapp_scan_state"
    )
    row = cur.fetchone()
    last_scan = row["last_scan"] if row else None

    # Total message count
    cur.execute("SELECT COUNT(*) AS count FROM whatsapp_messages")
    msg_count = cur.fetchone()["count"]

    # Contacts with messages
    cur.execute(
        "SELECT COUNT(DISTINCT contact_id) AS count FROM whatsapp_messages"
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
):
    """Get WhatsApp messages for a specific contact."""
    cur = conn.cursor()
    cur.execute(
        """SELECT wm.*, c.full_name AS contact_name
           FROM whatsapp_messages wm
           JOIN contacts c ON c.id = wm.contact_id
           WHERE wm.contact_id = %s
           ORDER BY wm.whatsapp_timestamp DESC, wm.captured_at DESC""",
        (contact_id,),
    )
    return [dict(r) for r in cur.fetchall()]
