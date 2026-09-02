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

def assemble_deep_story(result, *, agent_report:tuple[str,...]=(), later_outcomes:tuple[str,...]=(), previous:DecisionStory|None=None)->DecisionStory:
    """User-facing derived story; agent prose is explicitly non-repository truth."""
    sections=(
      StorySection("User request",tuple(StoryFinding(x.text,x.claim_kind,(f"intent:{x.id}",),x.uncertainty) for x in result.intent.elements)),
      StorySection("Midnight interpretation",tuple(StoryFinding(x.message,x.claim_kind,tuple(f"intent:{i}" for i in x.element_ids),x.uncertainty) for x in result.ambiguity.findings)),
      StorySection("Agent report",tuple(StoryFinding(x,ClaimKind.INFERRED,("agent-report",),"agent report is not repository truth") for x in agent_report) or (StoryFinding("No agent report",ClaimKind.UNKNOWN,(),"unavailable"),)),
      StorySection("Actual changes",tuple(StoryFinding(x.kind.value,x.claim_kind,x.raw_evidence,x.uncertainty) for x in result.structural.edits)),
      StorySection("Behavior and verification",tuple(StoryFinding(x.status.value,ClaimKind.DERIVED,x.evidence,x.uncertainty) for x in result.alignment)),
      StorySection("Uncertainty",tuple(StoryFinding(x,ClaimKind.UNKNOWN,(),"missing optional evidence") for x in result.gaps)),
      StorySection("Later outcomes",tuple(StoryFinding(x,ClaimKind.OBSERVED,(x,),"later outcome reference") for x in later_outcomes) or (StoryFinding("Later outcome unknown",ClaimKind.UNKNOWN,(),"unavailable"),)),)
    matrix=tuple(RequirementEvidence(c.requirement_id,c.evidence_id,c.relation,c.claim_kind,c.redacted) for c in __import__('midnight_performance.requirement_matrix',fromlist=['build_requirement_matrix']).build_requirement_matrix(result.requirements,result.links,result.alignment).entries)
    return DecisionStory(result.request.run_id,sections,matrix,tuple(e.id for e in result.trajectory.events) if result.trajectory else (),None,tuple(result.gaps)+((f"previous:{previous.run_id}",) if previous else ()))
