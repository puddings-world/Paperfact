"""An owned reader cache lock ends before an independent caller replaces its index."""

import gc
import os

import pytest
from test_document_reader import LOCAL, prepared

from paper_daily.document_reader import document_current


@pytest.mark.parametrize("existing_copy", [False, True])
def test_ready_document_releases_real_projection_index_before_return(tmp_path, existing_copy):
    _path, _journal, _blobs, reader, _alias, data = prepared(tmp_path)
    enabled = gc.isenabled()
    gc.disable()
    try:
        if existing_copy:
            assert reader.resolve(LOCAL).available
        result = reader.resolve(LOCAL)
        assert result.available and result.path.read_bytes() == data
        index = reader.projection_root / "projection-index.sqlite"
        previous = reader.projection_root / "previous-index.sqlite"
        original = index.read_bytes()
        os.replace(index, previous)
        assert previous.read_bytes() == original and not index.exists()
        os.replace(previous, index)
        assert index.read_bytes() == original
        assert document_current(result) and result.path.read_bytes() == data
    finally:
        reader.close()
        if enabled:
            gc.enable()
