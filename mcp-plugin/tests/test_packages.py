"""Verify the actual distributable packages and their self-contained references."""

import importlib.util
import json
from pathlib import Path
from wechat_bridge import __version__
import sys
import zipfile
import subprocess

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
PLUGIN_VERSION = json.loads((TOOLS.parent / "plugin.json").read_text(encoding="utf-8"))["version"]
sys.path.insert(0, str(TOOLS))
from package_checks import check, integration_document
from build_local_plugin import build as local
from build_remote_plugin import build as remote


@pytest.mark.parametrize("transport", ["local", "remote"])
def test_package_layout_and_references(tmp_path, transport):
    archive = tmp_path / "plugin.zip"
    if transport == "local":
        local(archive)
    else:
        remote("https://notify.example.com/wechat", archive)
    with zipfile.ZipFile(archive) as bundle:
        assert {name.split("/")[0] for name in bundle.namelist()} == {"wechat-notify-local"}
        assert not any(".private" in name or "__pycache__" in name for name in bundle.namelist())
        bundle.extractall(tmp_path / "unpacked")
    root = tmp_path / "unpacked/wechat-notify-local"
    manifest = check(root)
    assert manifest["version"] == PLUGIN_VERSION
    assert (root / "INSTALL.md").is_file()
    assert json.loads((root / "RELEASE.json").read_text())["plugin_version"] == manifest["version"]
    sys.path.insert(0, str(TOOLS.parents[1] / "scripts"))
    from check_documentation import check_archive

    check_archive(
        archive.read_bytes(),
        transport,
        server_version=__version__,
        plugin_version=manifest["version"],
    )
    assert (
        manifest["extensions"]["com.openai"]["interface"]["defaultPrompt"]
        == "通过微信通知插件查看服务状态。"
    )
    if transport == "local":
        assert (root / "server/api_errors.py").is_file()
    else:
        assert not (root / "server").exists()
        assert (
            json.loads((root / "mcp.json").read_text())["mcpServers"]["wechat-notify"]["url"]
            == "https://notify.example.com/wechat/mcp"
        )


def test_builders_refuse_to_write_inside_plugin_source():
    output = TOOLS.parent / "bad.zip"
    with pytest.raises(ValueError):
        local(output)
    with pytest.raises(ValueError):
        remote("https://example.com/wechat", output)
    assert not output.exists()


def test_remote_package_preserves_explicit_legacy_mcp_endpoint(tmp_path):
    path = tmp_path / "remote.zip"
    remote(
        "https://notify.example.com/bridge", path, mcp_url="https://notify.example.com/wechat/mcp"
    )
    with zipfile.ZipFile(path) as z:
        value = json.loads(z.read("wechat-notify-local/CONNECTION.json"))
        assert value["mcp_url"] == "https://notify.example.com/wechat/mcp"
    with pytest.raises(ValueError):
        remote("https://notify.example.com/bridge", path, mcp_url="https://other.example.com/mcp")


@pytest.mark.parametrize("transport", ["local", "remote"])
def test_extracted_local_plugin_builders_need_no_repository_docs(tmp_path, transport):
    original = local(tmp_path / "original.zip")
    with zipfile.ZipFile(original) as archive:
        archive.extractall(tmp_path / "unpacked")
    plugin = tmp_path / "unpacked/wechat-notify-local"
    assert not (plugin.parent / "docs").exists()
    output = tmp_path / "rebuilt.zip"
    command = [
        sys.executable,
        str(plugin / "tools" / ("build_" + transport + "_plugin.py")),
        "--output",
        str(output),
    ]
    if transport == "remote":
        command += [
            "--base-url",
            "https://notify.example.com/bridge",
            "--mcp-url",
            "https://notify.example.com/wechat/mcp",
        ]
    result = subprocess.run(command, cwd=plugin, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    from check_documentation import check_archive

    check_archive(
        output.read_bytes(), transport, server_version=__version__, plugin_version=PLUGIN_VERSION
    )


@pytest.mark.parametrize("canonical_exists", [True, False])
def test_checkout_docs_remain_authoritative_without_stale_bundle_fallback(
    tmp_path, canonical_exists
):
    (tmp_path / "server").mkdir()
    (tmp_path / "server/openapi.json").write_text("{}", encoding="utf-8")
    bundle = tmp_path / "plugin"
    bundle.mkdir()
    (bundle / "INSTALL.md").write_text("stale bundled copy", encoding="utf-8")
    if canonical_exists:
        canonical = tmp_path / "docs/integration/CLIENT-SETUP.md"
        canonical.parent.mkdir(parents=True)
        canonical.write_text("current [receiver](RECEIVERS.md)", encoding="utf-8")
        assert (
            integration_document(tmp_path, "CLIENT-SETUP.md", bundle=bundle)
            == b"current [receiver](F02-RECEIVERS.md)"
        )
    else:
        with pytest.raises(FileNotFoundError):
            integration_document(tmp_path, "CLIENT-SETUP.md", bundle=bundle)
