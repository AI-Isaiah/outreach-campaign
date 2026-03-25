"""Canonical enums for the outreach system.

Uses ``StrEnum`` so members compare equal to their string values,
meaning existing SQL queries, JSON payloads, and test assertions
continue to work without any changes.
"""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """Backport of StrEnum for Python < 3.11."""


class ContactStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    REPLIED_POSITIVE = "replied_positive"
    REPLIED_NEGATIVE = "replied_negative"
    NO_RESPONSE = "no_response"
    BOUNCED = "bounced"
    COMPLETED = "completed"
    UNSUBSCRIBED = "unsubscribed"


class Channel(StrEnum):
    EMAIL = "email"
    LINKEDIN_CONNECT = "linkedin_connect"
    LINKEDIN_MESSAGE = "linkedin_message"
    LINKEDIN_ENGAGE = "linkedin_engage"
    LINKEDIN_INSIGHT = "linkedin_insight"
    LINKEDIN_FINAL = "linkedin_final"


class DealStage(StrEnum):
    COLD = "cold"
    CONTACTED = "contacted"
    ENGAGED = "engaged"
    MEETING_BOOKED = "meeting_booked"
    NEGOTIATING = "negotiating"
    WON = "won"
    LOST = "lost"


class LifecycleStage(StrEnum):
    COLD = "cold"
    CONTACTED = "contacted"
    NURTURING = "nurturing"
    CLIENT = "client"
    CHURNED = "churned"


class ProductStage(StrEnum):
    DISCUSSED = "discussed"
    INTERESTED = "interested"
    DUE_DILIGENCE = "due_diligence"
    INVESTED = "invested"
    DECLINED = "declined"


class EmailStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    CATCH_ALL = "catch-all"
    RISKY = "risky"
    UNKNOWN = "unknown"
    UNVERIFIED = "unverified"


class EventType(StrEnum):
    EMAIL_SENT = "email_sent"
    CALL_BOOKED = "call_booked"
    CONTACT_CREATED = "contact_created"
    DEFERRED = "deferred"
    LIFECYCLE_CHANGED = "lifecycle_changed"
    LINKEDIN_CONNECT_DONE = "linkedin_connect_done"
    LINKEDIN_MESSAGE_DONE = "linkedin_message_done"
    LINKEDIN_ENGAGE_DONE = "linkedin_engage_done"
    LINKEDIN_INSIGHT_DONE = "linkedin_insight_done"
    LINKEDIN_FINAL_DONE = "linkedin_final_done"
    LINKEDIN_ACCEPTANCE_DETECTED = "linkedin_acceptance_detected"
    EXPANDI_CONNECTED = "expandi_connected"
    EXPANDI_MESSAGE_SENT = "expandi_message_sent"
    AUTO_ACTIVATED = "auto_activated"
