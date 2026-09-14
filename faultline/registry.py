"""Registry of available fault plugins.

Plugins self-register via the register decorator when their module is imported
(the faults package __init__ imports all built-ins). Third parties can add
faults by registering their own plugin class -- no engine changes needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:  # pragma: no cover
    from .faults.base import FaultPlugin

_REGISTRY: dict[str, type[FaultPlugin]] = {}
_T = TypeVar("_T", bound=type["FaultPlugin"])


class UnknownFaultError(KeyError):
    """Raised when an experiment references a fault type that is not registered."""


def register(plugin_cls: _T) -> _T:
    """Class decorator: register a fault plugin under its name attribute."""
    name = getattr(plugin_cls, "name", "") or ""
    if not name:
        raise ValueError(f"fault plugin {plugin_cls.__name__} has no 'name'")
    _REGISTRY[name] = plugin_cls
    return plugin_cls


def get(name: str) -> type[FaultPlugin]:
    """Look up a fault plugin class by registry key."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownFaultError(
            f"unknown fault type '{name}' (available: {', '.join(available())})"
        ) from None


def available() -> list[str]:
    """Sorted names of all registered fault types."""
    return sorted(_REGISTRY)
