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
def source(tmp_path, monkeypatch):
    for name in set(builder.FILES + list(builder.DOCS.values())):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture " + name, encoding="utf-8")
    (tmp_path / "server/openapi.json").write_text('{"info":{"version":"1.17.1"}}', encoding="utf-8")
    plugin = tmp_path / "mcp-plugin/plugin.json"
    plugin.parent.mkdir(parents=True, exist_ok=True)
    plugin.write_text('{"version":"1.11.0"}', encoding="utf-8")
    for name in ("frontend/render-docs.mjs", "frontend/src/shared/theme.css"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
    # These drift tests isolate the build manifest; the real Node renderer is tested separately.
    monkeypatch.setattr(
        builder,
        "render_public",
        lambda root, pages, release: {
            **{p["path"]: b"<h1>fixture</h1>" for p in pages},
            "style.css": b"body{}",
        },
    )
    builder.build(tmp_path)
    return tmp_path


@pytest.mark.parametrize("change", ["source", "json", "zip", "extra_member", "duplicate"])
def test_check_detects_drift_without_repairing_outputs(source, change):
    out = source / "server/src/wechat_bridge/web/admin"
    builder.build(source, check=True)
    if change == "source":
        (source / "docs/integration/README.md").write_text("changed", encoding="utf-8")
    elif change == "json":
        (out / "developer-docs.json").write_bytes(b"{}")
    elif change == "zip":
        (out / "developer-kit.zip").write_bytes(b"invalid")
    else:
        with zipfile.ZipFile(out / "developer-kit.zip", "a") as archive:
            if change == "duplicate":
                with pytest.warns(UserWarning):
                    archive.writestr("docs/integration/README.md", "duplicate")
            else:
                archive.writestr("unexpected.env", "fixture")
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    with pytest.raises(SystemExit, match="Stale developer assets"):
        builder.build(source, check=True)
    assert before == {p.name: p.read_bytes() for p in out.iterdir()}
    builder.build(source)
    builder.build(source, check=True)


def test_check_ignores_checkout_line_endings(source):
    path = source / "docs/integration/README.md"
    path.write_bytes(b"first\r\nsecond\r\n")
    builder.build(source)
    archive = source / "server/src/wechat_bridge/web/admin/developer-kit.zip"
    original = archive.read_bytes()
    path.write_bytes(b"first\nsecond\n")
    builder.build(source, check=True)
    builder.build(source)
    assert archive.read_bytes() == original


def test_unrelated_history_does_not_enter_or_invalidate_client_kit(source):
    path = source / "docs/history/new-evidence.md"
    path.parent.mkdir(parents=True)
    path.write_text("historical evidence", encoding="utf-8")
    builder.build(source, check=True)
    with zipfile.ZipFile(
        source / "server/src/wechat_bridge/web/admin/developer-kit.zip"
    ) as archive:
        assert path.relative_to(source).as_posix() not in archive.namelist()


@pytest.mark.parametrize("change", ["html", "missing", "renderer", "extra"])
def test_public_build_rejects_drift_without_node_or_repairs(source, monkeypatch, change):
    archive = source / "server/src/wechat_bridge/web/admin/public-docs.zip"
    with zipfile.ZipFile(archive) as z:
        entries = {n: z.read(n) for n in z.namelist()}
    if change == "renderer":
        (source / "frontend/render-docs.mjs").write_text("changed", encoding="utf-8")
    else:
        if change == "html":
            entries["index.html"] = b"tampered"
        elif change == "missing":
            del entries["openapi.json"]
        else:
            entries["private.json"] = b"{}"
        with zipfile.ZipFile(archive, "w") as z:
            for name, content in entries.items():
                z.writestr(name, content)
    before = archive.read_bytes()
    monkeypatch.setattr(builder, "render_public", lambda *args: pytest.fail("--check invoked Node"))
    with pytest.raises(SystemExit, match="Stale public documentation"):
        builder.build(source, check=True)
    assert archive.read_bytes() == before
