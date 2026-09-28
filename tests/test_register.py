def test_build_groups_routes_per_organisation(register):
    meta = register.meta()
    assert meta["register_date"] == "2026-09-28"
    assert meta["rows"] == "22"
    # "2i Limited" and "2I LIMITED" in Edinburgh are one organisation; K Line, 2 Sisters,
    # 1st Visa each collapse two route rows into one.
    assert meta["organisations"] == "18"


def test_exact_match_ignores_case_and_legal_suffix(register):
    [top, *_] = register.search("cake glory limited")
    assert top.name == "CAKE GLORY LTD LTD" and top.score == 100


def test_trading_name_resolves_to_legal_entity(register):
    result = register.check("Gurkha Swindon")
    assert result["verdict"] == "licensed"
    assert result["matches"][0]["name"] == "Everest Kitchen Ltd T/A Gurkha Swindon"


def test_multiple_routes_are_grouped(register):
    [top, *_] = register.search("2 Sisters Food Group")
    assert {r["route"] for r in top.routes} == {
        "Skilled Worker", "Global Business Mobility: Senior or Specialist Worker",
    }


def test_licensed_on_other_route_only(register):
    result = register.check("Mode Agence")
    assert result["verdict"] == "licensed_other_routes"


def test_route_parameter(register):
    assert register.check("Mode Agence", route="Creative Worker")["verdict"] == "licensed"


def test_b_rating_is_flagged(register):
    result = register.check("Example Widgets")
    assert result["verdict"] == "licensed"
    assert any("B-rated" in n for n in result["notes"])


def test_provisional_rating(register):
    result = register.check("Rainbow Polycarbonate Industry Trade",
                            route="Global Business Mobility: UK Expansion Worker")
    assert result["matches"][0]["routes"][0]["rating"] == "Provisional"


def test_partial_name_is_possible_match_not_licensed(register):
    result = register.check("Example Analytics Group")
    assert result["verdict"] == "possible_match"
    names = {m["name"] for m in result["matches"]}
    assert "Example Analytics Limited" in names


def test_typo_still_found(register):
    [top, *_] = register.search("F Secur")
    assert top.name == "F-Secure (UK) Limited"


def test_unknown_company(register):
    result = register.check("Totally Unrelated Quantum Bakery")
    assert result["verdict"] == "not_found"


def test_empty_query(register):
    assert register.search("  ltd ") == [] or register.search("") == []
