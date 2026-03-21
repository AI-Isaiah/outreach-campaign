# Spec 04: Email Deliverability & Compliance

**Priority:** P0 — Required before sending real outreach
**Estimated time:** 2–3 hours
**Prerequisite:** Spec 01 completed (double footer bug fixed there)

---

## Problem Statement

The email system has compliance gaps that risk CAN-SPAM fines and deliverability issues. The unsubscribe mechanism uses `mailto:` (requires the recipient to send an email to unsubscribe — not one-click). GDPR enforcement only checks at send time, not at the state machine level (so a 3rd email can be queued even if only 2 are allowed). Email send failures are silently swallowed with no retry or tracking. These issues must be fixed before sending outreach to real fund allocators.

---

## Task 1: Implement One-Click Unsubscribe

**Files to modify:**
- `src/services/compliance.py` (replace `build_unsubscribe_url`)
- `src/web/app.py` (add unsubscribe route)
- Create: `src/web/routes/unsubscribe.py`

**Current (non-compliant):**
```python
def build_unsubscribe_url(from_email: str) -> str:
    return f"mailto:{from_email}?subject=Unsubscribe"
```

**Fix — create token-based one-click unsubscribe:**

`src/services/compliance.py` changes:
```python
import hashlib
import hmac
import os

UNSUBSCRIBE_SECRET = os.getenv("UNSUBSCRIBE_SECRET", "change-me-in-production")

def generate_unsubscribe_token(contact_id: int, email: str) -> str:
    """Generate HMAC token for unsubscribe verification."""
    payload = f"{contact_id}:{email}"
    return hmac.new(
        UNSUBSCRIBE_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]

def build_unsubscribe_url(contact_id: int, email: str, base_url: str = None) -> str:
    """Build a one-click unsubscribe URL."""
    base = base_url or os.getenv("APP_BASE_URL", "http://localhost:8000")
    token = generate_unsubscribe_token(contact_id, email)
    return f"{base}/unsubscribe?id={contact_id}&token={token}"

def verify_unsubscribe_token(contact_id: int, email: str, token: str) -> bool:
    """Verify an unsubscribe token is valid."""
    expected = generate_unsubscribe_token(contact_id, email)
    return hmac.compare_digest(token, expected)
```

Create `src/web/routes/unsubscribe.py`:
```python
"""One-click unsubscribe endpoint (no auth required)."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from src.services.compliance import verify_unsubscribe_token, process_unsubscribe
from src.web.dependencies import get_db

router = APIRouter(tags=["unsubscribe"])

@router.get("/unsubscribe", dependencies=[])  # No auth required
def unsubscribe(
    id: int = Query(...),
    token: str = Query(...),
    conn=Depends(get_db),
):
    """One-click unsubscribe. Validates token and marks contact as unsubscribed."""
    cur = conn.cursor()
    cur.execute("SELECT id, email, email_normalized FROM contacts WHERE id = %s", (id,))
    contact = cur.fetchone()

    if not contact:
        raise HTTPException(404, "Contact not found")

    if not verify_unsubscribe_token(id, contact["email"], token):
        raise HTTPException(400, "Invalid unsubscribe link")

    # Process the unsubscribe
    process_unsubscribe(conn, contact["email_normalized"])

    return HTMLResponse(content="""
    <html>
    <body style="font-family: sans-serif; text-align: center; padding: 60px;">
        <h1>You've been unsubscribed</h1>
        <p>You will no longer receive emails from us.</p>
    </body>
    </html>
    """)
```

Register in `app.py` (outside auth middleware since recipients click this link):
```python
from src.web.routes import unsubscribe
app.include_router(unsubscribe.router)  # No /api prefix, no auth
```

**Update all places that call `build_unsubscribe_url`** to pass `contact_id` and `email` instead of just `from_email`. Check:
- `src/services/compliance.py` → `add_compliance_footer()` and `add_compliance_footer_html()`
- `src/services/email_sender.py` → wherever the footer is generated

Also add `List-Unsubscribe` header to outgoing emails in `email_sender.py`:
```python
msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
```

**Acceptance criteria:**
- [ ] Clicking unsubscribe URL marks contact as unsubscribed (no email required)
- [ ] Token prevents abuse (can't unsubscribe arbitrary contacts)
- [ ] Unsubscribe page shows confirmation HTML
- [ ] Invalid tokens return 400
- [ ] List-Unsubscribe header present in all outgoing emails
- [ ] List-Unsubscribe-Post header present (RFC 8058 compliance)
- [ ] Unsubscribe endpoint has NO auth requirement

---

## Task 2: Add GDPR Limit Check to State Machine

**File:** `src/services/state_machine.py`

**Bug:** The GDPR email limit (max 2 emails for GDPR contacts) is only checked at send time in email_sender.py. The state machine can advance a contact to step 3, which queues a 3rd email that only gets caught when attempting to send. This wastes a queue slot and is confusing.

**Fix:** Add the GDPR check inside the state machine's `advance_to_next_step` logic:

```python
from src.services.compliance import check_gdpr_email_limit, is_contact_gdpr

def _can_advance_to_next_email(conn, contact_id: int, campaign_id: int) -> bool:
    """Check if contact can receive another email (GDPR limit)."""
    if not is_contact_gdpr(conn, contact_id):
        return True  # Non-GDPR contacts have no email limit

    return check_gdpr_email_limit(conn, contact_id, campaign_id)
```

Call this before advancing to the next step in the transition function. If the limit is reached, transition to `completed` instead of advancing.

**Acceptance criteria:**
- [ ] GDPR contacts are auto-completed when they hit the 2-email limit
- [ ] Non-GDPR contacts are unaffected
- [ ] State machine logs WHY it completed the contact (GDPR limit reached)
- [ ] Test: enroll a GDPR contact, send 2 emails, verify 3rd step is skipped

---

## Task 3: Track Email Send Attempts in Database

**File:** `src/services/email_sender.py`

**Current:** The `send_email()` function returns `True/False` but the result is ignored by CLI commands. Failed emails are silently lost.

**Fix:** Log every send attempt (success or failure) as an event:

```python
def send_email(conn, contact_id, campaign_id, template_id, ...):
    # ... existing send logic ...

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(from_email, to_email, msg.as_string())

        # Log success
        log_event(
            conn, contact_id, "email_sent",
            campaign_id=campaign_id,
            template_id=template_id,
            metadata=json.dumps({"to": to_email, "subject": subject, "status": "delivered"}),
        )
        logger.info("Email sent to contact %s", contact_id)  # No PII in logs
        return True

    except smtplib.SMTPException as e:
        # Log failure
        log_event(
            conn, contact_id, "email_failed",
            campaign_id=campaign_id,
            template_id=template_id,
            metadata=json.dumps({"error": str(e), "error_type": type(e).__name__}),
        )
        logger.exception("SMTP error sending to contact %s", contact_id)
        return False
```

**Acceptance criteria:**
- [ ] Every send attempt creates an event (email_sent or email_failed)
- [ ] Failed emails include error type and message in event metadata
- [ ] Logger uses contact_id, NOT email address (no PII in logs)
- [ ] Existing event queries can filter by event_type to see failures

---

## Task 4: Add Email Retry with Backoff

**File:** `src/services/email_sender.py`

Add simple retry logic for transient SMTP failures:

```python
import time

MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 30]  # seconds

def send_email_with_retry(conn, contact_id, campaign_id, template_id, ...):
    """Send email with exponential backoff retry on transient failures."""
    for attempt in range(MAX_RETRIES):
        try:
            result = _send_single_email(conn, contact_id, campaign_id, template_id, ...)
            if result:
                return True
        except smtplib.SMTPServerDisconnected:
            # Transient — retry
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    "SMTP disconnected for contact %s, retrying in %ss (attempt %s/%s)",
                    contact_id, delay, attempt + 1, MAX_RETRIES,
                )
                time.sleep(delay)
                continue
        except smtplib.SMTPAuthenticationError:
            # Permanent — don't retry
            logger.error("SMTP auth failed — check credentials")
            return False
        except smtplib.SMTPRecipientsRefused:
            # Permanent — don't retry, mark as bounced
            log_event(conn, contact_id, "email_bounced", campaign_id=campaign_id)
            return False

    # All retries exhausted
    log_event(
        conn, contact_id, "email_failed",
        campaign_id=campaign_id,
        metadata=json.dumps({"error": "max_retries_exhausted", "attempts": MAX_RETRIES}),
    )
    return False
```

**Acceptance criteria:**
- [ ] Transient SMTP errors (disconnect) trigger retry with delay
- [ ] Permanent errors (auth failure, recipient refused) do NOT retry
- [ ] Bounced emails log a `email_bounced` event
- [ ] Max 3 retries with 5s, 15s, 30s delays
- [ ] All retry attempts are logged

---

## Task 5: Add SPF/DKIM/DMARC Setup Guide

**File:** Create `docs/email_setup.md`

This isn't code — it's documentation for the user to configure their sending domain. Generate a guide covering:

1. **SPF record** — What TXT record to add for their domain
2. **DKIM** — How to generate DKIM keys and add the DNS record
3. **DMARC** — Recommended DMARC policy (start with `p=none` for monitoring)
4. **Testing** — How to verify setup using mail-tester.com
5. **Google Workspace specifics** — Since the platform uses Gmail SMTP/drafts

**Acceptance criteria:**
- [ ] Guide created with step-by-step DNS configuration
- [ ] Includes example DNS records
- [ ] Includes verification commands/tools
- [ ] Mentions Gmail-specific considerations

---

## Verification Checklist

```bash
# Test unsubscribe flow
# 1. Check that outgoing emails include List-Unsubscribe header
# 2. Visit the unsubscribe URL from an email
# 3. Verify contact is marked unsubscribed in DB

# Test GDPR limits
# 1. Create a GDPR contact
# 2. Send 2 emails
# 3. Verify state machine completes the contact (no 3rd email queued)

# Run tests
make test
```

- [ ] One-click unsubscribe works end-to-end
- [ ] List-Unsubscribe header in all outgoing emails
- [ ] GDPR limit enforced at state machine level
- [ ] All send attempts tracked in events table
- [ ] Retry logic handles transient SMTP failures
- [ ] No PII in application logs
