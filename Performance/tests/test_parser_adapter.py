from midnight_performance import parse_source
def test_parser_adapter_is_bounded_and_honest_about_fallbacks():
    assert parse_source("a.py","def f(): pass").tree is not None
    assert "unsupported" in parse_source("a.ts","let x=1").gap
    assert "parsed" in parse_source("a.py","bad(").gap
    assert "bound" in parse_source("a.py","x"*10,maximum_bytes=2).gap
