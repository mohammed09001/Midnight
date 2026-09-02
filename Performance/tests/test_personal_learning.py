from datetime import datetime,timezone
from midnight_performance import ExperienceRecord, match_history, profile, suggest_next_time
def r(id,task="bug",component="api",provider="codex"): return ExperienceRecord(id,"u","p",component,task,provider,datetime(2026,1,1,tzinfo=timezone.utc),{"rework":1},("run:"+id,))
def test_profile_scopes_privacy_and_records_missingness():
    item=profile((r("a"),),project_id="p",user_id="u",raw_allowed=False)
    assert item.privacy_restricted and item.scope==("project:p",) and item.sample_size==1
def test_matching_exposes_differences_and_suggestions_need_repeated_nonconflicting_evidence():
    matches=match_history(r("q"),(r("a"),r("b")))
    assert matches[0].matched_dimensions==("project","component","task_type","provider")
    suggestion=suggest_next_time("verification","run boundary test",("task:bug",),matches)
    assert suggestion and suggestion.confidence>0
    assert suggest_next_time("verification","x",(),matches,contradictory_evidence=("counterexample",)) is None
