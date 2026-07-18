"""Compatibility re-export of the standard-library-only core domain."""

import noema_mail_core as _core
from noema_mail_core import *  # noqa: F403

__all__ = _core.__all__
