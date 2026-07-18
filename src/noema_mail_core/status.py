"""V1 draft lifecycle without any delivery states."""

from __future__ import annotations

from enum import StrEnum

from .exceptions import InvalidTransitionError


class DraftStatus(StrEnum):
    """States available to a draft in version 1."""

    NEW = "new"
    STAGED = "staged"
    SYNCED_TO_GMX = "synced_to_gmx"
    MODIFIED = "modified"
    INVALIDATED = "invalidated"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[DraftStatus, frozenset[DraftStatus]] = {
    DraftStatus.NEW: frozenset(
        {DraftStatus.STAGED, DraftStatus.INVALIDATED, DraftStatus.FAILED}
    ),
    DraftStatus.STAGED: frozenset(
        {DraftStatus.SYNCED_TO_GMX, DraftStatus.INVALIDATED, DraftStatus.FAILED}
    ),
    DraftStatus.SYNCED_TO_GMX: frozenset(
        {DraftStatus.MODIFIED, DraftStatus.INVALIDATED, DraftStatus.FAILED}
    ),
    DraftStatus.MODIFIED: frozenset(),
    DraftStatus.INVALIDATED: frozenset(),
    DraftStatus.FAILED: frozenset(),
}


def transition(current: DraftStatus, target: DraftStatus) -> DraftStatus:
    """Validate and return the target of a draft lifecycle transition."""

    if not isinstance(current, DraftStatus) or not isinstance(target, DraftStatus):
        raise InvalidTransitionError("status transitions require DraftStatus values")
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(
            f"transition from {current.value!r} to {target.value!r} is not allowed"
        )
    return target
