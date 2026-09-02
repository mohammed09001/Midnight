from midnight_performance import ProductTruthCheck, final_product_truth, improvement_corpus, qualify_fixture
def test_local_improvement_corpus_covers_adversarial_and_deep_analysis_cases():
    corpus=improvement_corpus()
    assert len(corpus)>=5 and sum(x.adversarial for x in corpus)>=3
    result=qualify_fixture(corpus[1],("structural","not_path_proof"))
    assert result.passed
    assert not qualify_fixture(corpus[0],("nested",)).passed
def test_final_gate_requires_explicit_evidence_and_keeps_failures_visible():
    gate=final_product_truth((ProductTruthCheck("no-agent-hosting",True,("interaction_policy",),"static contract"),ProductTruthCheck("privacy",False,("missing-check",),"not exercised")))
    assert not gate.passed
