from app.staging.delta import StoredRow, StagingCounts, classify
from app.staging.hashing import content_hash

CFG = "cfg0"


def _stored(pid, ch, status="active", pk=1):
    return StoredRow(pk=pk, product_id=pid, content_hash=ch, config_hash=CFG,
                     status=status, snapshot={})


def _products(*items):
    return [{"id": pid, "title": t} for pid, t in items]


class TestClassify:
    def test_first_run_inserts_everything(self):
        products = _products(("1", "A"), ("2", "B"))
        delta = classify(products, {}, CFG)
        assert [u.product_id for u in delta.upserts] == ["1", "2"]
        assert all(u.insert and u.write_history for u in delta.upserts)
        assert delta.enqueue == products
        assert delta.counts.new == 2

    def test_identical_rerun_only_touches(self):
        products = _products(("1", "A"))
        stored = {"1": _stored("1", content_hash(products[0]), pk=7)}
        delta = classify(products, stored, CFG)
        assert delta.upserts == [] and delta.enqueue == []
        assert delta.touches == [7]
        assert delta.counts.unchanged == 1

    def test_content_change_enqueues_with_history(self):
        old = {"id": "1", "title": "A"}
        new = {"id": "1", "title": "B"}
        delta = classify([new], {"1": _stored("1", content_hash(old), pk=7)}, CFG)
        assert delta.upserts[0].write_history is True
        assert delta.enqueue == [new]
        assert delta.counts.changed == 1

    def test_config_only_change_enqueues_without_history(self):
        product = {"id": "1", "title": "A"}
        delta = classify([product], {"1": _stored("1", content_hash(product), pk=7)}, "cfgNEW")
        assert delta.upserts[0].write_history is False
        assert delta.upserts[0].config_hash == "cfgNEW"
        assert delta.counts.changed == 1

    def test_removal_when_active_row_absent(self):
        stored = {"1": _stored("1", "x", pk=7), "2": _stored("2", "y", pk=8)}
        delta = classify([], stored, CFG)
        assert delta.removals == [7, 8]
        assert delta.counts.removed == 2

    def test_removed_row_absent_again_is_noop(self):
        stored = {"1": _stored("1", "x", status="removed", pk=7)}
        delta = classify([], stored, CFG)
        assert delta.removals == []
        assert delta.counts.removed == 0

    def test_reactivation_with_equal_hashes_flips_only(self):
        product = {"id": "1", "title": "A"}
        stored = {
            "1": StoredRow(pk=7, product_id="1", content_hash=content_hash(product),
                           config_hash=CFG, status="removed", snapshot={}),
        }
        delta = classify([product], stored, CFG)
        assert delta.upserts == []
        assert delta.reactivations == [7]
        assert delta.enqueue == [product]
        assert delta.counts.reactivated == 1

    def test_reactivation_with_changed_content_upserts_with_history(self):
        old = {"id": "1", "title": "A"}
        new = {"id": "1", "title": "B"}
        stored = {
            "1": StoredRow(pk=7, product_id="1", content_hash=content_hash(old),
                           config_hash=CFG, status="removed", snapshot=old),
        }
        delta = classify([new], stored, CFG)
        assert len(delta.upserts) == 1
        assert delta.upserts[0].write_history is True
        assert delta.reactivations == []
        assert delta.counts.reactivated == 1

    def test_missing_or_invalid_ids_fail(self):
        delta = classify([{"title": "no id"}, {"id": "", "t": 1}, [1, 2]], {}, CFG)
        assert delta.counts.failed == 3
        assert delta.enqueue == []

    def test_duplicate_ids_first_wins_rest_fail(self):
        products = _products(("1", "A")) + [{"id": "1", "title": "dup"}]
        delta = classify(products, {}, CFG)
        assert delta.enqueue == [products[0]]
        assert delta.counts.failed == 1
        assert delta.counts.new == 1

    def test_counts_default_zero(self):
        assert StagingCounts().new == 0
