from midnight_performance import DeepAnalysisRequest, TraceCandidate, TraceSupportEvidence, analyze_deep, link_from_candidate
def test_identity_corruption_is_an_explicit_integrity_failure_not_a_story_success():
    result=analyze_deep(DeepAnalysisRequest("p","bad-id","Build cache.",after="def cache(): pass",privacy_redacted=True,corrupt_requirement_identity=True))
    assert not result.integrity.qualifies and result.story is None and "link integrity failed" in result.gaps
def test_unsupported_parser_and_agent_prose_do_not_become_repository_truth():
    result=analyze_deep(DeepAnalysisRequest("p","ts","Build cache.",path="app.ts",after="export const cache=1",privacy_redacted=True))
    assert not result.structural.supported and any("unsupported" in edit.uncertainty for edit in result.structural.edits)
def test_typed_support_rejects_wrong_symbol_mutation():
    candidate=TraceCandidate("requirement:1","code:right",.5,(),"test","1",__import__('midnight_performance').ClaimKind.INFERRED,"test")
    try: link_from_candidate(candidate,typed_support=TraceSupportEvidence("p","r","c","code:wrong","vcs","ast"))
    except ValueError: pass
    else: raise AssertionError("wrong-symbol typed support must be rejected")
