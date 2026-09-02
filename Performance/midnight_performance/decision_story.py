"""User-facing, evidence-drillable decision-story projections."""
from __future__ import annotations
from dataclasses import dataclass
from .contracts import ClaimKind
from .trajectory import Trajectory
from .journey_intelligence import FrictionMetrics
DECISION_STORY_VERSION="1"
@dataclass(frozen=True, slots=True)
class StoryFinding:
    text:str; claim_kind:ClaimKind; evidence:tuple[str,...]; uncertainty:str
@dataclass(frozen=True, slots=True)
class StorySection:
    title:str; findings:tuple[StoryFinding,...]
@dataclass(frozen=True, slots=True)
class RequirementEvidence:
    requirement_id:str|None; evidence_id:str; verdict:str; claim_kind:ClaimKind; redacted:bool=False
@dataclass(frozen=True, slots=True)
class DecisionStory:
    run_id:str; sections:tuple[StorySection,...]; matrix:tuple[RequirementEvidence,...]; timeline:tuple[str,...]; friction:FrictionMetrics|None; gaps:tuple[str,...]
    def text(self)->str:
        return "\n".join(f"{section.title}: " + "; ".join(finding.text for finding in section.findings) for section in self.sections)
def build_story(run_id:str, *, findings:tuple[StoryFinding,...], matrix:tuple[RequirementEvidence,...], trajectory:Trajectory|None=None, friction:FrictionMetrics|None=None, later_outcomes:tuple[str,...]=())->DecisionStory:
    sections=(StorySection("What happened",findings),StorySection("Later outcomes",tuple(StoryFinding(x,ClaimKind.OBSERVED,(x,),"sibling outcome reference") for x in later_outcomes) or (StoryFinding("Later outcome unknown",ClaimKind.UNKNOWN,(),"no later outcome reference"),)))
    timeline=tuple(f"{event.id}:{event.kind.value}" for event in trajectory.events) if trajectory else ()
    gaps=(trajectory.ordering_uncertainty if trajectory else ("trajectory unavailable",)) + tuple(item.evidence_id+":redacted" for item in matrix if item.redacted)
    return DecisionStory(run_id,sections,matrix,timeline,friction,gaps)
