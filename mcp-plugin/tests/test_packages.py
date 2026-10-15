"""Verify the actual distributable packages and their self-contained references."""

import importlib.util
import json
from pathlib import Path
from wechat_bridge import __version__
import sys
import zipfile

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from package_checks import check
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
    assert manifest["version"] == "1.11.0"
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
