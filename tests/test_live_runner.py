"""Focused tests for live runner response validation."""

from scripts.test_live_llm import _compare_interpretations, _numeric_equal


def test_numeric_equal_rejects_non_finite_values():
    assert not _numeric_equal("nan", 100.0)
    assert not _numeric_equal("inf", 100.0)


def test_compare_interpretations_detects_wrong_directive():
    expected = [{
        "note_index": 0,
        "applies": True,
        "directive_type": "no_charge_window",
        "structured_adjustment": {"hours": [14, 15]},
    }]
    actual = [{
        "note_index": 0,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
    }]

    errors = _compare_interpretations(actual, expected)

    assert errors
    assert any("directive[0].applies" in error for error in errors)


def test_compare_interpretations_accepts_numeric_tolerance():
    expected = [{
        "note_index": 0,
        "applies": True,
        "directive_type": "solar_reduction",
        "structured_adjustment": {"hours": [13], "factor": 0.2},
    }]
    actual = [{
        "note_index": 0,
        "applies": True,
        "directive_type": "solar_reduction",
        "structured_adjustment": {"hours": [13], "factor": 0.2001},
    }]

    assert _compare_interpretations(actual, expected) == []