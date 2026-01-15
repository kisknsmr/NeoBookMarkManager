"""
Deprecated shim for AI classification module.
Use services.legacy.ai_classifier instead.
"""

from __future__ import annotations

import warnings

from services.legacy.ai_classifier import *  # noqa: F401,F403

warnings.warn(
    "services.ai_classifier is deprecated; use services.legacy.ai_classifier instead.",
    DeprecationWarning,
    stacklevel=2,
)
