from .aalcr import AALCRAdapter
from .aime25 import AIME25Adapter
from .base import BenchmarkAdapter
from .gaia import GAIAAdapter
from .gpqa import GPQAAdapter
from .hle import HLEAdapter
from .livebench import LiveBenchAdapter
from .math import MathAdapter
from .super_gpqa import SuperGPQAAdapter

ADAPTER_REGISTRY: dict[str, type[BenchmarkAdapter]] = {
    "math": MathAdapter,
    "gaia": GAIAAdapter,
    "hle": HLEAdapter,
    "gpqa": GPQAAdapter,
    "aime25": AIME25Adapter,
    "livebench": LiveBenchAdapter,
    "aalcr": AALCRAdapter,
    "super_gpqa": SuperGPQAAdapter,
}

__all__ = [
    "AALCRAdapter",
    "ADAPTER_REGISTRY",
    "AIME25Adapter",
    "BenchmarkAdapter",
    "GAIAAdapter",
    "GPQAAdapter",
    "HLEAdapter",
    "LiveBenchAdapter",
    "MathAdapter",
    "SuperGPQAAdapter",
]
