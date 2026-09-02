from midnight_performance import DeepAnalysisRequest, analyze_deep, final_product_truth, improvement_corpus, qualify_fixture
def test_executable_corpus_runs_real_pipeline_and_gate_rejects_adversarial_break():
    results=tuple(qualify_fixture(x) for x in improvement_corpus())
    assert all(x.passed for x in results)
    assert final_product_truth(results[:-1]).passed
    assert not final_product_truth(results).passed
def test_deep_pipeline_truthfully_retains_missing_evidence_and_replays():
    request=DeepAnalysisRequest("p","r","Build cache.",after="def cache(): pass",privacy_redacted=True)
    first=analyze_deep(request); second=analyze_deep(request)
    assert first == second and {"verification unavailable","trajectory unavailable"} <= set(first.gaps)
    assert first.integrity.qualifies and first.story is not None
