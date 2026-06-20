"""AgentROI: Self-improving agent-swarm profiler."""
from .loop import AgentROILoop
from .memory import MemoryManager, make_memory_manager
from .memory_backends import ACEPlaybookBackend, JSONMemoryBackend
from .memory_consumers import (
    ActionBlocklist,
    CompositeConsumer,
    EvidenceSeeder,
    PromptInjector,
    RoutingDecider,
    default_consumer,
)
from .memory_protocol import MemoryBackend, MemoryConsumer, compose_outputs
from .schemas import (
    AgentRole,
    ConsumerContext,
    ConsumerOutput,
    EventType,
    MemoryEntry,
    MemoryEntryType,
    RetrievalQuery,
    RetrievalStrategy,
    ROIReport,
    WasteType,
)
from .tracer import SwarmTracer

__all__ = [
    "AgentROILoop",
    "MemoryManager",
    "make_memory_manager",
    "ACEPlaybookBackend",
    "JSONMemoryBackend",
    "MemoryBackend",
    "MemoryConsumer",
    "compose_outputs",
    "PromptInjector",
    "RoutingDecider",
    "ActionBlocklist",
    "EvidenceSeeder",
    "CompositeConsumer",
    "default_consumer",
    "AgentRole",
    "ConsumerContext",
    "ConsumerOutput",
    "EventType",
    "MemoryEntry",
    "MemoryEntryType",
    "RetrievalQuery",
    "RetrievalStrategy",
    "ROIReport",
    "WasteType",
    "SwarmTracer",
]
