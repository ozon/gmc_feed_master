import dataclasses

import pytest

from app.ingest import IngestReport
from app.ingest.report import SourceField
from app.pipeline import RunState


class TestSourceField:
    def test_frozen_with_defaults(self):
        sf = SourceField(name="shipping", kind="group", sub_fields=("country", "price"))
        assert sf.name == "shipping"
        assert sf.kind == "group"
        assert sf.sub_fields == ("country", "price")
        assert SourceField(name="id", kind="scalar").sub_fields == ()

    def test_is_frozen(self):
        sf = SourceField(name="id", kind="scalar")
        with pytest.raises(dataclasses.FrozenInstanceError):
            sf.name = "other"


class TestIngestReportSourceFields:
    def test_defaults_to_empty_list(self):
        assert IngestReport().source_fields == []

    def test_instances_do_not_share_list(self):
        a = IngestReport()
        b = IngestReport()
        a.source_fields.append(SourceField(name="id", kind="scalar"))
        assert b.source_fields == []


class TestRunStateSourceFields:
    def test_defaults_to_empty_list(self):
        assert RunState().source_fields == []

    def test_instances_do_not_share_list(self):
        a = RunState()
        b = RunState()
        a.source_fields.append(SourceField(name="id", kind="scalar"))
        assert b.source_fields == []
