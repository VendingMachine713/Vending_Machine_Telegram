"""VM Intelligence shared platform service."""
__version__ = "6.0.0"

from .events import Event, Telemetry
from .store import IntelligenceStore
from .analytics import IntelligenceAnalyzer
from .recommendations import RecommendationEngine

__all__ = [
    "Event",
    "Telemetry",
    "IntelligenceStore",
    "IntelligenceAnalyzer",
    "RecommendationEngine",
]
