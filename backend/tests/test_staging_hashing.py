from app.staging.hashing import canonical_json, content_hash, strip_derived


class TestStripDerived:
    def test_removes_top_level_underscore_keys(self):
        assert strip_derived({"id": "1", "_prov": "x"}) == {"id": "1"}

    def test_removes_nested_and_inside_lists(self):
        value = {
            "shipping": [{"country": "US", "_i": "x"}, {"country": "DE"}],
            "meta": {"keep": 1, "_drop": 2},
        }
        assert strip_derived(value) == {
            "shipping": [{"country": "US"}, {"country": "DE"}],
            "meta": {"keep": 1},
        }

    def test_leaves_scalars_untouched(self):
        assert strip_derived("x") == "x"
        assert strip_derived(42) == 42
        assert strip_derived(None) is None


class TestCanonicalJson:
    def test_key_order_independent(self):
        assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})

    def test_nested_keys_sorted(self):
        assert canonical_json({"o": {"y": 1, "x": 2}}) == canonical_json({"o": {"x": 2, "y": 1}})

    def test_unicode_preserved_and_compact(self):
        assert canonical_json({"t": "schön"}) == '{"t":"schön"}'


class TestContentHash:
    def test_is_sha256_hexdigest(self):
        digest = content_hash({"id": "1"})
        assert len(digest) == 64
        int(digest, 16)

    def test_sidecars_do_not_change_hash(self):
        plain = {"id": "1", "title": "Shirt"}
        decorated = {**plain, "_category_provenance": "auto"}
        assert content_hash(plain) == content_hash(decorated)

    def test_content_change_changes_hash(self):
        assert content_hash({"title": "a"}) != content_hash({"title": "b"})
