"""Target adapters: how the system under test is reached and (optionally) owned."""

from .base import Target, TargetError, TargetStartError
from .external_target import ExternalTarget
from .subprocess_target import SubprocessTarget

__all__ = ["ExternalTarget", "SubprocessTarget", "Target", "TargetError", "TargetStartError"]
