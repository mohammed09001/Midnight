"""Read-only Ask Me, draft preflight, and qualified advisor projections."""
from __future__ import annotations
from dataclasses import dataclass
from .contracts import ClaimKind
from .prompt_analysis import analyze_prompt
from .ambiguity_analysis import AmbiguityReport, analyze_ambiguity
from .similarity import Experience, retrieve
@dataclass(frozen=True, slots=True)
class AskResult:
    answer:str; evidence:tuple[str,...]; claim_kind:ClaimKind=ClaimKind.DERIVED
@dataclass(frozen=True, slots=True)
class PreflightReport:
    prompt:str; requirement_count:int; ambiguities:tuple[str,...]; claim_kind:ClaimKind=ClaimKind.DERIVED; ambiguity_report:AmbiguityReport|None=None
def ask_read_only(query:str, evidence:tuple[str,...])->AskResult:
    terms=set(query.lower().split()); matches=tuple(x for x in evidence if terms & set(x.lower().split()))
    return AskResult("matching retained evidence" if matches else "no matching retained evidence",matches,ClaimKind.DERIVED if matches else ClaimKind.UNKNOWN)
def preflight(prompt:str)->PreflightReport:
    features,metrics=analyze_prompt(prompt)
    report=analyze_ambiguity(features.intent_contract) if features.intent_contract else None
    messages=features.ambiguities + tuple(item.message for item in report.findings if item.status.value == "open") if report else features.ambiguities
    return PreflightReport(prompt,len(features.requirements),messages,ClaimKind.DERIVED,report)
def advise(query:Experience, history:tuple[Experience,...])->AskResult:
    matches=retrieve(query,history,top_k=3)
    return AskResult("similar historical experiences; not a recommendation",tuple(x.prompt_run_id for x in matches),ClaimKind.INFERRED if matches else ClaimKind.UNKNOWN)
