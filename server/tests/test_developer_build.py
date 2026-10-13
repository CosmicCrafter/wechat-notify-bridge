"""Generated documentation must fail closed when its source or output changes."""

import importlib.util
from pathlib import Path
import zipfile
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "developer_builder", ROOT / "server/scripts/build_developer_kit.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture
def source(tmp_path):
    for name in builder.FILES + [
        "docs/integration/README.md",
        "docs/server/API.md",
        "docs/server/TASK-CARDS.md",
    ]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture " + name, encoding="utf-8")
    builder.build(tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    "change", ["source", "new_doc", "removed_doc", "json", "zip", "extra_member", "duplicate"]
)
def test_check_detects_drift_without_repairing_outputs(source, change):
    out = source / "server/src/wechat_bridge/web/admin"
    builder.build(source, check=True)
    if change == "source":
        (source / "README.md").write_text("changed", encoding="utf-8")
    elif change == "new_doc":
        (source / "docs/new.md").write_text("new", encoding="utf-8")
    elif change == "removed_doc":
        (source / "docs/new.md").write_text("old", encoding="utf-8")
        builder.build(source)
        (source / "docs/new.md").unlink()
    elif change == "json":
        (out / "developer-docs.json").write_bytes(b"{}")
    elif change == "zip":
        (out / "developer-kit.zip").write_bytes(b"invalid")
    else:
        with zipfile.ZipFile(out / "developer-kit.zip", "a") as archive:
            if change == "duplicate":
                with pytest.warns(UserWarning):
                    archive.writestr("README.md", "duplicate")
            else:
                archive.writestr("unexpected.env", "fixture")
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    with pytest.raises(SystemExit, match="Stale developer assets"):
        builder.build(source, check=True)
    assert before == {p.name: p.read_bytes() for p in out.iterdir()}
    builder.build(source)
    builder.build(source, check=True)


def test_check_ignores_checkout_line_endings(source):
    path = source / "README.md"
    path.write_bytes(b"first\r\nsecond\r\n")
    builder.build(source)
    archive = source / "server/src/wechat_bridge/web/admin/developer-kit.zip"
    original = archive.read_bytes()
    path.write_bytes(b"first\nsecond\n")
    builder.build(source, check=True)
    builder.build(source)
    assert archive.read_bytes() == original
