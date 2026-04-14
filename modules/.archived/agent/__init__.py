"""
Agent Module — Smart Teacher Intelligent Agent

Contains the core agent components:
- perception: User understanding
- memory: Student profiling & history
- reasoning: Logical analysis
- decision: Action selection (GA/PSO)
- brain: Orchestration
"""

from agent.perception import (
    Perception,
    PerceptionResult,
    Intent,
    get_perception,
)

__all__ = [
    "Perception",
    "PerceptionResult",
    "Intent",
    "get_perception",
]

__version__ = "0.1.0"
