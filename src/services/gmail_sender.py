"""Send emails via Gmail API using OAuth tokens."""

import base64
import logging
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

logger = logging.getLogger(__name__)


class GmailSendError(Exception):
    """Raised when Gmail API send fails."""
    pass


class TokenRefreshError(Exception):
    """Raised when OAuth token refresh fails."""
    pass


class GmailSender:
    """Send emails via Gmail API using OAuth tokens.

    The sender does not persist tokens to the database — the caller
    handles persistence after refresh.
    """

    SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        token_expiry: datetime,
        client_id: str,
        client_secret: str,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expiry = token_expiry
        self.client_id = client_id
        self.client_secret = client_secret

    def is_token_expired(self) -> bool:
        """Check if the access token is expired (with 60s buffer)."""
        if not self.token_expiry:
            return True
        now = datetime.now(timezone.utc)
        expiry = self.token_expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return now >= (expiry - __import__("datetime").timedelta(seconds=60))

    def refresh(self) -> dict:
        """Refresh access token using refresh_token.

        Returns {"access_token": str, "expires_in": int}.
        Caller persists to DB and updates this instance's access_token.
        """
        if not self.refresh_token:
            raise TokenRefreshError("No refresh token available")

        response = httpx.post(
            self.TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
        )

        if response.status_code != 200:
            error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            error_desc = error_data.get("error_description", response.text[:200])
            raise TokenRefreshError(f"Token refresh failed: {error_desc}")

        data = response.json()
        return {
            "access_token": data["access_token"],
            "expires_in": data.get("expires_in", 3600),
        }

    def send(self, to: str, subject: str, html_body: str, from_name: str = "", from_email: str = "") -> dict:
        """Send an email via Gmail API.

        Returns {"message_id": str, "thread_id": str}.
        Raises GmailSendError on failure.
        """
        # Build MIME message
        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["Subject"] = subject
        if from_name and from_email:
            msg["From"] = f"{from_name} <{from_email}>"
        elif from_email:
            msg["From"] = from_email

        # Add plain text version (strip HTML)
        import re
        plain_text = re.sub(r"<[^>]+>", "", html_body)
        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        # Encode to base64url
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        # Send via Gmail API
        response = httpx.post(
            self.SEND_URL,
            json={"raw": raw},
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=30,
        )

        if response.status_code == 401:
            raise TokenRefreshError("Access token expired or revoked")
        if response.status_code == 429:
            raise GmailSendError("Gmail API rate limit exceeded")
        if response.status_code != 200:
            error_text = response.text[:500]
            raise GmailSendError(f"Gmail API error ({response.status_code}): {error_text}")

        data = response.json()
        logger.info("Gmail send success: message_id=%s to=%s", data.get("id"), to)
        return {
            "message_id": data.get("id", ""),
            "thread_id": data.get("threadId", ""),
        }
