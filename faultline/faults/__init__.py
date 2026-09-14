"""Built-in fault plugins.

Importing this package registers every built-in fault with the registry. Add a
new fault by dropping a module here that defines a FaultPlugin subclass decorated
with @register -- nothing else needs to change.
"""

from . import cpu_pressure, memory_pressure, network_delay, process_kill  # noqa: F401
from .base import FaultError, FaultPlugin

__all__ = ["FaultError", "FaultPlugin"]
