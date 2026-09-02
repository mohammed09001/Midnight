"""Transparent prompt structural extraction and quality metrics."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .intent_contract import IntentContract, IntentKind, extract_intent_contract

class RequirementType(str, Enum): ACTION="action"; CONSTRAINT="constraint"; ACCEPTANCE="acceptance"; VERIFICATION="verification"; REFERENCE="reference"; UNKNOWN="unknown"
@dataclass(frozen=True, slots=True)
class ExtractedRequirement:
    text:str; start:int; end:int; type:RequirementType; importance:str|None; expected_evidence:tuple[str,...]; ambiguity:tuple[str,...]=()
@dataclass(frozen=True, slots=True)
class PromptFeatures:
    version:str; requirements:tuple[ExtractedRequirement,...]; ambiguity_markers:tuple[str,...]; task_category:str; intent_contract:IntentContract|None=None
@dataclass(frozen=True, slots=True)
class PromptMetrics:
    version:str; clarity:float; specificity:float; scope_definition:float; constraint_quality:float; verification_quality:float; ambiguity:float
def analyze_prompt(text:str)->tuple[PromptFeatures,PromptMetrics]:
    contract=extract_intent_contract(text); req=[]; ambiguity=[]
    kind_map={IntentKind.CONSTRAINT:RequirementType.CONSTRAINT,IntentKind.ACCEPTANCE:RequirementType.ACCEPTANCE,IntentKind.VERIFICATION:RequirementType.VERIFICATION,IntentKind.REFERENCE:RequirementType.REFERENCE}
    for element in contract.elements:
        line=element.text
        low=line.lower(); typ=RequirementType.CONSTRAINT if any(x in low for x in ("must","do not","avoid")) else RequirementType.VERIFICATION if any(x in low for x in ("test","verify","check")) else RequirementType.ACTION
        typ=kind_map.get(element.kind,typ)
        if any(x in low for x in ("maybe","somehow","etc","as needed")): ambiguity.append(line)
        req.append(ExtractedRequirement(line,element.span.start,element.span.end,typ,"high" if "must" in low else None,("verification" if typ is RequirementType.VERIFICATION else "change",), ("ambiguous wording",) if line in ambiguity else ()))
    total=max(len(contract.elements),1); constraints=sum(x.type is RequirementType.CONSTRAINT for x in req); verify=sum(x.type is RequirementType.VERIFICATION for x in req)
    metrics=PromptMetrics("1",round(1-len(ambiguity)/total,3),round(min(1,len(req)/3),3),round(min(1,len(req)/2),3),round(constraints/total,3),round(verify/total,3),round(len(ambiguity)/total,3))
    return PromptFeatures("2",tuple(req),tuple(ambiguity),"development_request",contract),metrics
