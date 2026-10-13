"""Agent registry. Agents are small, single-purpose and side-effect free: they read the shared
context and *return* artifacts, decisions and proposed workspace changes. They never write to
the workspace or call humans' approval paths directly - the engine governs that."""
from __future__ import annotations

from ..model import AgentResult, Stage


class Agent:
    name = "agent"

    def run(self, ctx, stage: Stage) -> AgentResult:  # pragma: no cover - interface
        raise NotImplementedError


def build_registry(generator=None) -> dict[str, Agent]:
    from ..packs import TemplateGenerator
    from .analysis import CodebaseAnalyst, PlannerAgent, RequirementsAgent
    from .build import ApiSpecAgent, ImplementerAgent, ImplementerSafeMode, TestAuthorAgent
    from .delivery import DocsAgent, DocsMinimalAgent, ReleaseAgent
    from .design import ArchitectAgent
    from .verify import SecurityReviewAgent, VerifierAgent
    gen = generator or TemplateGenerator()
    agents = [RequirementsAgent(), CodebaseAnalyst(), PlannerAgent(), ArchitectAgent(gen), ApiSpecAgent(),
              ImplementerAgent(gen), ImplementerSafeMode(gen), TestAuthorAgent(gen), VerifierAgent(),
              SecurityReviewAgent(), DocsAgent(), DocsMinimalAgent(), ReleaseAgent()]
    return {a.name: a for a in agents}
