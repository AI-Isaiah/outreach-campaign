"""Gmail API integration for creating email drafts.

Uses OAuth 2.0 to authenticate with the user's Gmail account and create
drafts that can be reviewed and sent manually from the Gmail UI.
"""

from __future__ import annotations

import base64
import logging
import os
from email.mime.multipart import MIMEMultipart

from src.services.retry import retry_on_failure
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Scopes needed: compose drafts and check if they've been sent
SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]


class GmailDrafter:
    """Manages Gmail OAuth and draft creation."""

    def __init__(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = ".gmail_token.json",
    ):
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self._service = None

    @classmethod
    def from_db_tokens(
        cls,
        access_token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
    ) -> "GmailDrafter":
        """Create a GmailDrafter from DB-stored OAuth tokens.

        Builds a google.oauth2.credentials.Credentials object directly
        instead of reading from filesystem. Works in serverless environments.
        """
        from google.oauth2.credentials import Credentials

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        instance = cls.__new__(cls)
        instance.credentials_path = None
        instance.token_path = None
        instance._service = None
        instance._db_credentials = creds
        return instance

    def is_authorized(self) -> bool:
        """Check if we have valid Gmail credentials."""
        db_creds = getattr(self, "_db_credentials", None)
        if db_creds is not None:
            return db_creds.token is not None
        if not self.token_path or not self.token_path.exists():
            return False
        try:
            creds = self._load_credentials()
            return creds is not None and creds.valid
        except Exception:
            return False

    def _load_credentials(self):
        """Load credentials from the token file."""
        from google.oauth2.credentials import Credentials

        if not self.token_path.exists():
            return None
        creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            self._save_credentials(creds)
        return creds

    def _save_credentials(self, creds):
        """Save credentials to the token file."""
        self.token_path.write_text(creds.to_json())

    def get_authorization_url(self) -> str:
        """Start the OAuth flow and return the authorization URL.

        The user visits this URL, grants access, and receives an auth code
        to pass to ``handle_callback()``.
        """
        from google_auth_oauthlib.flow import Flow

        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"Gmail credentials file not found: {self.credentials_path}. "
                "Download it from Google Cloud Console."
            )

        flow = Flow.from_client_secrets_file(
            str(self.credentials_path),
            scopes=SCOPES,
            redirect_uri=f"{_BACKEND_URL}/api/gmail/callback",
        )
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return auth_url

    def handle_callback(self, auth_code: str) -> bool:
        """Exchange the authorization code for credentials.

        Args:
            auth_code: the code from the OAuth redirect

        Returns:
            True if credentials were successfully saved.
        """
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_secrets_file(
            str(self.credentials_path),
            scopes=SCOPES,
            redirect_uri=f"{_BACKEND_URL}/api/gmail/callback",
        )
        flow.fetch_token(code=auth_code)
        self._save_credentials(flow.credentials)
        self._service = None  # reset cached service
        return True

    def _get_service(self):
        """Get or create the Gmail API service."""
        if self._service is not None:
            return self._service

        from googleapiclient.discovery import build

        creds = getattr(self, "_db_credentials", None) or self._load_credentials()
        if creds is None:
            raise RuntimeError("Gmail not authorized. Call get_authorization_url() first.")

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    @retry_on_failure(max_retries=3, backoff_base=1.0, exceptions=(Exception,))
    def create_draft(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ) -> str:
        """Create a Gmail draft and return the draft ID.

        Args:
            to_email: recipient email address
            subject: email subject
            body_text: plain text body
            body_html: optional HTML body

        Returns:
            The Gmail draft ID string.
        """
        service = self._get_service()

        msg = MIMEMultipart("alternative")
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        if body_html:
            msg.attach(MIMEText(body_html, "html", "utf-8"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        draft = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}},
        ).execute()

        draft_id = draft["id"]
        logger.info("Created Gmail draft %s for %s", draft_id, to_email)
        return draft_id

    def check_draft_status(self, draft_id: str) -> str:
        """Check if a draft still exists (meaning it hasn't been sent yet).

        Returns:
            'draft' if it still exists, 'sent' if it was sent/deleted,
            'error' if there was a non-404 API error.
        """
        from googleapiclient.errors import HttpError

        service = self._get_service()
        try:
            service.users().drafts().get(userId="me", id=draft_id).execute()
            return "draft"
        except HttpError as e:
            if e.resp.status == 404:
                return "sent"
            logger.warning("Gmail API error checking draft %s: %s", draft_id, e)
            return "error"
        except Exception:
            logger.exception("Unexpected error checking draft %s", draft_id)
            return "error"

    def create_batch_drafts(self, drafts: list[dict]) -> list[dict]:
        """Create multiple Gmail drafts.

        Args:
            drafts: list of dicts with keys: to_email, subject, body_text, body_html

        Returns:
            List of dicts with keys: to_email, draft_id, success, error
        """
        results = []
        for d in drafts:
            try:
                draft_id = self.create_draft(
                    to_email=d["to_email"],
                    subject=d["subject"],
                    body_text=d["body_text"],
                    body_html=d.get("body_html"),
                )
                results.append({
                    "to_email": d["to_email"],
                    "draft_id": draft_id,
                    "success": True,
                })
            except Exception as e:
                logger.exception("Failed to create draft for %s", d["to_email"])
                results.append({
                    "to_email": d["to_email"],
                    "draft_id": None,
                    "success": False,
                    "error": str(e),
                })
        return results
