"""Category plugin process semantics, sidecar exclusion, config-hash reprocess."""

import copy
import logging

from app.plugins.runtime import RunContext
from app.staging.hashing import content_hash
from tests.category_plugin_module import category_plugin as cp

CONFIG = {"rules": [
    {"id": "r-auto", "source_field": "product_type", "operator": "eq",
     "source_value": "Shoes", "taxonomy_id": "166", "is_excluded": False},
]}
DATA = {"assignments": {"p-manual": "53"}}


def _ctx(product=None):
    return RunContext(
        client_id=0, feed_source_id=0, run_id=0,
        logger=logging.getLogger("category-test"),
        original_product=copy.deepcopy(product or {}),
    )


class TestProcess:
    def test_manual_assignment_wins(self):
        plugin = cp.CategoryPlugin()
        state = plugin.prepare_run(CONFIG, DATA, _ctx())
        product = {"id": "p-manual", "product_type": "Shoes", "title": "Boot"}
        result = plugin.process(product, CONFIG, DATA, _ctx(product), state=state)
        assert result["google_product_category"] == "53"
        assert result["_category_provenance"] == "manual"
        assert "_category_rule_id" not in result

    def test_auto_rule_sets_provenance_and_rule_id(self):
        plugin = cp.CategoryPlugin()
        state = plugin.prepare_run(CONFIG, DATA, _ctx())
        product = {"id": "p-auto", "product_type": "Shoes"}
        result = plugin.process(product, CONFIG, DATA, _ctx(product), state=state)
        assert result["google_product_category"] == "166"
        assert result["_category_provenance"] == "auto"
        assert result["_category_rule_id"] == "r-auto"

    def test_uncategorized_product_untouched(self):
        plugin = cp.CategoryPlugin()
        state = plugin.prepare_run(CONFIG, DATA, _ctx())
        product = {"id": "p-none", "product_type": "Socks"}
        result = plugin.process(product, CONFIG, DATA, _ctx(product), state=state)
        assert result == product
        assert "_category_provenance" not in result

    def test_empty_config_passthrough(self):
        plugin = cp.CategoryPlugin()
        product = {"id": "p1", "title": "x"}
        assert plugin.process(product, {}, {}, _ctx(product)) is product

    def test_original_product_not_mutated(self):
        plugin = cp.CategoryPlugin()
        state = plugin.prepare_run(CONFIG, DATA, _ctx())
        product = {"id": "p-auto", "product_type": "Shoes"}
        original = copy.deepcopy(product)
        plugin.process(product, CONFIG, DATA, _ctx(product), state=state)
        assert product == original

    def test_process_without_state_builds_from_config_data(self):
        plugin = cp.CategoryPlugin()
        product = {"id": "p-auto", "product_type": "Shoes"}
        result = plugin.process(product, CONFIG, DATA, _ctx(product))
        assert result["_category_provenance"] == "auto"


class TestSidecarExclusion:
    def test_sidecars_do_not_change_content_hash(self):
        with_sidecars = {
            "id": "p1", "title": "Shoe", "google_product_category": "166",
            "_category_provenance": "auto", "_category_rule_id": "r-auto",
        }
        without = {"id": "p1", "title": "Shoe", "google_product_category": "166"}
        assert content_hash(with_sidecars) == content_hash(without)

    def test_sidecars_never_reach_xml(self):
        from app.export.renderer import ChannelMetadata, render_feed
        from tests.support_registry import minimal_gmc_registry

        registry = minimal_gmc_registry()
        product = {
            "id": "p1", "title": "Shoe", "google_product_category": "166",
            "_category_provenance": "auto", "_category_rule_id": "r-auto",
        }
        xml = render_feed([product], registry, ChannelMetadata("t", "l", "d")).decode()
        assert "<g:google_product_category>166</g:google_product_category>" in xml
        assert "_category_provenance" not in xml
        assert "_category_rule_id" not in xml


class TestConfigHashReprocess:
    def _bundle(self, resolved_config, resolved_data):
        return {
            "pipeline": None,
            "instances": [{
                "position": 0, "plugin": "category", "plugin_version": "1.0.0",
                "instance_config": {},
                "resolved_config": resolved_config,
                "resolved_data": resolved_data,
            }],
        }

    def test_unchanged_bundle_hash_stable(self):
        assert content_hash(self._bundle(CONFIG, DATA)) == content_hash(
            self._bundle(copy.deepcopy(CONFIG), copy.deepcopy(DATA))
        )

    def test_rule_edit_changes_hash(self):
        edited = {"rules": [{**CONFIG["rules"][0], "taxonomy_id": "53"}]}
        assert content_hash(self._bundle(edited, DATA)) != content_hash(
            self._bundle(CONFIG, DATA)
        )

    def test_assignment_edit_changes_hash(self):
        edited = {"assignments": {"p-manual": "166"}}
        assert content_hash(self._bundle(CONFIG, edited)) != content_hash(
            self._bundle(CONFIG, DATA)
        )
