"""Small deterministic improvement corpus and final product-truth audit."""
from __future__ import annotations
from dataclasses import dataclass
from .contracts import ClaimKind
IMPROVEMENT_QUALIFICATION_VERSION="1"
@dataclass(frozen=True, slots=True)
class ImprovementFixture:
    id:str; prompt:str; before:str|None; after:str|None; expected:tuple[str,...]; adversarial:bool=False
@dataclass(frozen=True, slots=True)
class QualificationResult:
    fixture_id:str; passed:bool; exercised:tuple[str,...]; limitation:str
@dataclass(frozen=True, slots=True)
class ProductTruthCheck:
    name:str; passed:bool; evidence:tuple[str,...]; limitation:str
@dataclass(frozen=True, slots=True)
class ProductTruthReport:
    checks:tuple[ProductTruthCheck,...]
    @property
    def passed(self)->bool: return all(item.passed for item in self.checks)
def improvement_corpus()->tuple[ImprovementFixture,...]:
    return (
        ImprovementFixture("nested-intent","Build cache.\n  - Do not send secrets.\n  - Verify cache.",None,None,("nested","span","constraint")),
        ImprovementFixture("path-false-positive","Do not change config.py","def feature():\n return 1","def feature():\n return 2",("structural","not_path_proof"),True),
        ImprovementFixture("passing-divergence","Cache returns normalized key.",None,None,("oracle_gap","divergence"),True),
        ImprovementFixture("manual-concurrent","Fix parser.",None,None,("manual_not_agent","ordering_gap"),True),
        ImprovementFixture("privacy-redacted","Handle account.",None,None,("redacted","bounded_reference"),True),
    )
def qualify_fixture(fixture:ImprovementFixture, exercised:tuple[str,...])->QualificationResult:
    expected=set(fixture.expected); actual=set(exercised)
    return QualificationResult(fixture.id,expected<=actual,tuple(sorted(actual)),"fixture qualification only; it does not prove unexercised real-world providers")
def final_product_truth(checks:tuple[ProductTruthCheck,...])->ProductTruthReport:
    if not checks: raise ValueError("final gate requires explicit check evidence")
    return ProductTruthReport(checks)
