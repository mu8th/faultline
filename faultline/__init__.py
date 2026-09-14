"""FaultLine -- hypothesis-driven chaos testing for local systems.

Instead of only asking "how much load can this take?", FaultLine asks "does the
system behave the way I said it would when specific things break?" An experiment
declares SLO hypotheses up front, then FaultLine injects real faults (process
kills, CPU/memory pressure, network delay and drops) against a running target,
probes it continuously, and grades every hypothesis pass/fail with evidence.

Everything runs locally: targets are spawned as child processes or reached at an
existing URL, faults are bounded by design, and the API binds to 127.0.0.1 only.
"""

from . import faults as _faults  # noqa: F401 -- importing registers built-in plugins
from .engine import ExperimentError, run_experiment
from .models import ExperimentSpec, load_experiment
from .registry import UnknownFaultError, available

__version__ = "0.1.0"

__all__ = [
    "ExperimentError",
    "ExperimentSpec",
    "UnknownFaultError",
    "available",
    "load_experiment",
    "run_experiment",
    "__version__",
]
