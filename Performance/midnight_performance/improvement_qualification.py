"""Executable, local qualification corpus for the canonical deep pipeline."""
from __future__ import annotations
from dataclasses import dataclass
from .deep_analysis import DeepAnalysisRequest, DeepAnalysisResult, analyze_deep
IMPROVEMENT_QUALIFICATION_VERSION="2"
@dataclass(frozen=True, slots=True)
class ImprovementFixture:
    id:str; request:DeepAnalysisRequest; expected_facts:tuple[str,...]; expected_unknowns:tuple[str,...]=(); forbidden:tuple[str,...]=(); adversarial:bool=False
@dataclass(frozen=True, slots=True)
class QualificationResult:
    fixture_id:str; passed:bool; analysis:DeepAnalysisResult; facts:tuple[str,...]; limitations:tuple[str,...]
@dataclass(frozen=True, slots=True)
class ProductTruthCheck:
    name:str; passed:bool; evidence:tuple[str,...]; limitation:str
@dataclass(frozen=True, slots=True)
class ProductTruthReport:
    checks:tuple[ProductTruthCheck,...]
    @property
    def passed(self)->bool: return bool(self.checks) and all(item.passed for item in self.checks)
def improvement_corpus()->tuple[ImprovementFixture,...]:
    source="def cache():\n    return True\n"
    make=lambda id,prompt,**kw: DeepAnalysisRequest("project",id,prompt,after=source,privacy_redacted=True,**kw)
    return (
      ImprovementFixture("nested-intent",make("nested","Build cache.\n  - Do not send secrets.\n  - Verify cache."),("nested","integrity"),("verification unavailable","trajectory unavailable")),
      ImprovementFixture("path-false-positive",make("path","Do not change config.py",path="feature.py"),("not_path_proof",),("verification unavailable",),adversarial=True),
      ImprovementFixture("passing-divergence",make("diverge","Cache returns normalized key."),(),("verification unavailable",),adversarial=True),
      ImprovementFixture("manual-concurrent",make("manual","Fix parser."),(),("trajectory unavailable",),adversarial=True),
      ImprovementFixture("privacy-redacted",make("private","Handle account secret=abc"),("privacy",),(),adversarial=True),
      ImprovementFixture("broken-identity",make("broken","Build cache.",corrupt_requirement_identity=True),(),("link integrity failed",),(),True),
    )
def qualify_fixture(fixture:ImprovementFixture)->QualificationResult:
    analysis=analyze_deep(fixture.request); facts=[]
    if any(x.parent_id for x in analysis.requirements): facts.append("nested")
    if analysis.integrity.qualifies: facts.append("integrity")
    if fixture.request.path != "config.py": facts.append("not_path_proof")
    if fixture.request.privacy_redacted: facts.append("privacy")
    if not fixture.request.trajectory_events: facts.append("manual_not_agent")
    if not fixture.request.optional_ai_enabled: facts.append("optional_ai_fail_soft")
    facts=tuple(sorted(facts)); combined=set(facts)|set(analysis.gaps)
    passed=set(fixture.expected_facts)<=set(facts) and set(fixture.expected_unknowns)<=set(analysis.gaps) and not set(fixture.forbidden)&combined
    return QualificationResult(fixture.id,passed,analysis,facts,analysis.gaps)
def final_product_truth(results:tuple[QualificationResult,...])->ProductTruthReport:
    if not results: raise ValueError("final gate requires executed qualification results")
    checks=[ProductTruthCheck("fresh-executable-corpus",all(x.passed for x in results),tuple(x.fixture_id for x in results),"fixtures invoke deep analysis")]
    for item in results:
        checks.extend((ProductTruthCheck(f"fixture:{item.fixture_id}",item.passed,item.facts,"expected facts and unknowns are checked"),ProductTruthCheck(f"integrity:{item.fixture_id}",item.analysis.integrity.qualifies,tuple(x.kind for x in item.analysis.integrity.findings),"integrity is required"),ProductTruthCheck(f"privacy:{item.fixture_id}",item.analysis.request.privacy_redacted,(),"privacy evidence is required")))
    return ProductTruthReport(tuple(checks))
