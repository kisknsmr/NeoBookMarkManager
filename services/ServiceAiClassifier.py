"""Deprecated shim for AI classification module.

Use services.legacy.ServiceAiClassifierLegacy instead.
"""

from __future__ import annotations

import warnings

from services.legacy.ServiceAiClassifierLegacy import *  # noqa: F401,F403

warnings.warn(
    "services.ServiceAiClassifier is deprecated; use services.legacy.ServiceAiClassifierLegacy instead.",
    DeprecationWarning,
    stacklevel=2,
)
