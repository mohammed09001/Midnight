from midnight_performance import BehaviorVerificationEvidence, CoverageKind, OracleSource, link_verification
def test_typed_requirement_verification_links_keep_unassigned_and_reported_evidence_visible():
    reported=BehaviorVerificationEvidence("v1",None,OracleSource.TEST,False,(),(),None,None,(),"reported")
    link=link_verification(None,None,reported,specificity=.2)
    assert link.requirement_id is None and not link.executed and link.coverage is CoverageKind.UNKNOWN
    specific=link_verification("requirement:1","behavior:1",BehaviorVerificationEvidence("v2","behavior:1",OracleSource.TEST,True,(),(),"ok",True,(),"scoped"))
    assert specific.specificity == 1 and specific.coverage is CoverageKind.POSITIVE
