from dataclasses import dataclass

from app.export.service import _findings_diff


@dataclass
class _Row:
    code: str
    severity: str
    product_id: str
    field: str | None


def test_groups_by_rule_and_computes_buckets():
    a = [
        _Row("rule_a", "warning", "p1", "title"),
        _Row("rule_a", "warning", "p2", "title"),
    ]
    b = [
        _Row("rule_a", "warning", "p1", "title"),  # persisted
        _Row("rule_b", "critical", "p3", "gtin"),  # added
    ]

    result = _findings_diff(a, b, a_qc=True, b_qc=True)

    assert result.totals.model_dump() == {"added": 1, "fixed": 1, "persisted": 1}
    assert [r.code for r in result.rules] == ["rule_b", "rule_a"]  # critical before warning
    rule_a = next(r for r in result.rules if r.code == "rule_a")
    assert (rule_a.added, rule_a.fixed, rule_a.persisted) == (0, 1, 1)
    assert rule_a.sample_fixed == ["p2"]
    assert rule_a.sample_persisted == ["p1"]
    rule_b = next(r for r in result.rules if r.code == "rule_b")
    assert (rule_b.added, rule_b.fixed, rule_b.persisted) == (1, 0, 0)
    assert rule_b.sample_added == ["p3"]


def test_equal_severity_sorts_by_code():
    a = []
    b = [
        _Row("rule_b", "info", "p1", None),
        _Row("rule_a", "info", "p2", None),
    ]

    result = _findings_diff(a, b, a_qc=True, b_qc=True)

    assert [r.code for r in result.rules] == ["rule_a", "rule_b"]


def test_caps_samples_but_keeps_totals():
    a = []
    b = [_Row("rule_a", "info", f"p{i}", None) for i in range(25)]

    result = _findings_diff(a, b, a_qc=True, b_qc=True)

    rule = result.rules[0]
    assert rule.added == 25
    assert len(rule.sample_added) == 20


def test_not_qc_side_yields_empty():
    result = _findings_diff([_Row("rule_a", "info", "p1", None)], [], a_qc=False, b_qc=True)
    assert result.a_qc is False
    assert result.totals.model_dump() == {"added": 0, "fixed": 0, "persisted": 0}
    assert result.rules == []
