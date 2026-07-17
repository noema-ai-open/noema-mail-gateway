"""Initial domain boundary for NOEMA Mail Gateway.

Fable 5 must approve the final domain model before implementation expands.
No IMAP, SMTP, OpenClaw, MCP, browser, or Thunderbird dependency belongs here.
"""

from dataclasses import dataclass
from enum import StrEnum


class DraftStatus(StrEnum):
    CREATED = "created"
    SYNCHRONIZED = "synchronized"
    CHANGED = "changed"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SENDING = "sending"
    SENT = "sent"
    APPROVAL_EXPIRED = "approval_expired"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DraftReference:
    """Minimal immutable reference used by tests and architecture work."""

    draft_id: str
    version: int
    status: DraftStatus
