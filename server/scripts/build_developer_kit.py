"""Build or check developer assets against their public source files."""

import argparse
import json
import hashlib
import posixpath
import re
import shutil
import subprocess
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
# Reader-oriented allowlist: historical designs and server deployment sources stay in the repository.
FILES = [
    "docs/tutorials/FIRST-INTEGRATION.md",
    "docs/explanations/RELIABLE-CONVERSATIONS.md",
    "docs/reference/HTTP-CONTRACT.md",
    "docs/MAINTAINER.md",
    "docs/server/CONFIGURATION.md",
    "docs/product-v3/OPERATIONS.md",
    "docs/integration/README.md",
    "docs/integration/CLIENT-SETUP.md",
    "docs/integration/AI-HOSTS.md",
    "docs/integration/HTTP.md",
    "docs/integration/RECEIVERS.md",
    "docs/server/API.md",
    "docs/server/BOTS.md",
    "docs/server/FEISHU.md",
    "docs/server/TASK-CARDS.md",
    "docs/server/IMAGES.md",
    "docs/server/CHAT.md",
    "docs/server/REMOTE-MCP.md",
    "docs/server/MCP-EVENTS.md",
    "docs/server/DELIVERY-RELIABILITY.md",
    "docs/wechat-markdown/微信Markdown排版指南.md",
    "server/openapi.json",
    "examples/python/notify_bridge.py",
]
FILES += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "docs/assets").glob("*.svg"))]
SKILL_PREFIX = "mcp-plugin/skills/wechat-notify/"
FILES += [SKILL_PREFIX + "SKILL.md"] + [
    p.relative_to(ROOT).as_posix()
    for p in sorted((ROOT / SKILL_PREFIX / "references").glob("*.md"))
]
DOCS = {
    "guide": "docs/integration/README.md",
    "setup": "docs/integration/CLIENT-SETUP.md",
    "api": "docs/server/API.md",
    "cards": "docs/server/TASK-CARDS.md",
    "operations": "docs/product-v3/OPERATIONS.md",
    "ai": "docs/integration/AI-HOSTS.md",
    "http": "docs/integration/HTTP.md",
}
INTRO = """# 通知桥接入文档包

先读 [接入指南](docs/integration/README.md)，按用途选择 [AI 安装](docs/integration/CLIENT-SETUP.md) 或 [HTTP 接入](docs/integration/HTTP.md)。
匿名下载只含通用资料，没有实例配置。若管理员提供 DEPLOYMENT.json / CONNECTION.json，使用其中实际 base_url 和 mcp_url，不自行拼接迁移后的 MCP 地址。
版本与公开源指纹见 RELEASE.json；接口规范 server/openapi.json，示例 examples/python/notify_bridge.py。
AI 可从 llms.txt 按需查阅同源接入资料；本 ZIP 是通用 Markdown/接口/示例包，网页增强资源由 /docs/ 提供。
本包不含真实 Key、MCP 可执行插件或服务端安装程序。请管理员另行提供私有凭据或从向导下载对应接入包。
未收录的维护/源码资料链接会明确指向完整仓库；历史设计和验收记录不混入本包。
"""


def markdown_title(content, fallback):
    return next(
        (line[2:] for line in content.decode("utf-8").splitlines() if line.startswith("# ")),
        fallback,
    )


def validate_diagram(text):
    """Only passive SVG primitives authored with the documentation may be published."""
    import xml.etree.ElementTree as ET

    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("Active SVG declaration")
    allowed = {
        "svg",
        "title",
        "desc",
        "defs",
        "marker",
        "path",
        "rect",
        "g",
        "text",
        "tspan",
        "line",
        "polygon",
        "circle",
    }
    root = ET.fromstring(text)
    attributes = {
        "viewBox",
        "role",
        "aria-labelledby",
        "id",
        "width",
        "height",
        "rx",
        "fill",
        "x",
        "y",
        "font-family",
        "font-size",
        "stroke",
        "stroke-width",
        "stroke-dasharray",
        "marker-end",
        "marker-start",
        "markerWidth",
        "markerHeight",
        "refX",
        "refY",
        "orient",
        "d",
        "points",
        "x1",
        "x2",
        "y1",
        "y2",
        "cx",
        "cy",
        "r",
        "text-anchor",
        "dominant-baseline",
        "dy",
        "transform",
    }
    for node in root.iter():
        if (
            not node.tag.startswith("{http://www.w3.org/2000/svg}")
            or node.tag.split("}")[-1] not in allowed
        ):
            raise ValueError("Non-passive documentation diagram")
        for name, value in node.attrib.items():
            if (
                name not in attributes
                or name.split("}")[-1].lower().startswith("on")
                or name.split("}")[-1] in {"href", "style"}
                or re.search(r"(?:https?:|data:|javascript:|url\((?!#[\w-]+\)))", value, re.I)
            ):
                raise ValueError("Active or external documentation diagram attribute")


def public_contents(entries):
    """Project the existing public allowlist, preserving one Markdown maintenance source."""
    from urllib.parse import quote

    mapping = {name: name.removeprefix("docs/") for name in entries}
    mapping["server/openapi.json"] = "openapi.json"
    mapping["docs/product-v3/OPERATIONS.md"] = "operations/ADMIN.md"
    for name in entries:
        if name.startswith(SKILL_PREFIX):
            mapping[name] = "skill/" + name.removeprefix(SKILL_PREFIX)
    mapping.pop("START-HERE.md")
    mapping.pop("llms.txt", None)
    public, pages = {}, []

    def markdown(text, source, destination, html=False):
        def link(match):
            href = match[1]
            if re.match(r"\w+:|#", href):
                return match[0]
            path, separator, anchor = href.partition("#")
            target = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
            if target not in mapping:
                raise ValueError("Public documentation target is not allowlisted: " + target)
            output = mapping[target]
            if html and output.endswith(".md") and not output.startswith("skill/"):
                output = output[:-3] + ".html"
            relative = posixpath.relpath(output, posixpath.dirname(destination) or ".")
            return (
                "](" + quote(relative, safe="/") + (separator + anchor if separator else "") + ")"
            )

        return re.sub(r"\]\(([^)]+)\)", link, text)

    for source, destination in mapping.items():
        value = entries[source]
        if source.endswith(".md"):
            text = value.decode("utf-8")
            public[destination] = markdown(text, source, destination).encode("utf-8")
            title = next(
                (line[2:] for line in text.splitlines() if line.startswith("# ")), destination
            )
            page = destination[:-3] + ".html"
            if source.startswith(SKILL_PREFIX):
                continue
            pages.append(
                dict(
                    path=page,
                    title=title,
                    markdown_path=destination,
                    markdown=markdown(text, source, page, True),
                )
            )
        else:
            public[destination] = value
    guide = "docs/integration/README.md"
    text = entries[guide].decode("utf-8")
    public["index.md"] = markdown(text, guide, "index.md").encode("utf-8")
    pages.insert(
        0,
        dict(
            path="index.html",
            title="公开开发文档",
            markdown_path="index.md",
            markdown=markdown(text, guide, "index.html", True),
        ),
    )
    return public, pages


def navigation(root):
    return json.loads((root / "frontend/docs/navigation.json").read_text(encoding="utf-8"))


def ai_index(groups, release, targets, *, schema, example, rules=()):
    """Same index facts and titles, projected into website or portable package paths."""
    text = [
        "# Notify Bridge 开发者文档",
        f"> 服务 {release['server_version']} · MCP 插件 {release['plugin_version']}。统一消息中转站。",
        "阅读公开资料无需登录；调用 API 仍须应用授权。实际 base_url / mcp_url 与凭据由管理员提供，不从文档地址猜测 MCP 地址。",
        "先核对身份和授权，再 dry_run；真实发送另需明确授权。共享应用 Key 不证明宿主聊天身份；protected 会话另需 X-Notify-Receiver。自动唤醒和工具调用分别验收。",
    ]
    for group in groups:
        text.append("## " + group["group"])
        text.append(
            "\n".join(
                f"- [{label}]({targets[path]}): {summary}"
                for path, label, summary in group["pages"]
            )
        )
    if rules:
        text.extend(
            [
                "## Skill 规则与引用（只读，不授予调用权限）",
                "\n".join(f"- [{label}]({path})" for path, label in rules),
            ]
        )
    text.extend(
        [
            "## 规范与示例",
            f"- [OpenAPI 3.1]({schema})\n- [Python 示例]({example})\n- [版本与源指纹](RELEASE.json)",
        ]
    )
    return ("\n\n".join(text) + "\n").encode("utf-8")


def render_public(root, pages, release):
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Public HTML build requires Node and frontend/npm ci; --check does not")
    data = dict(
        pages=pages,
        release=release,
        theme=(root / "frontend/src/shared/theme.css").read_text(encoding="utf-8"),
        images=[name.removeprefix("docs/") for name in FILES if name.endswith(".svg")],
    )
    result = subprocess.run(
        [node, str(root / "frontend/render-docs.mjs"), str(ROOT / "frontend")],
        input=json.dumps(data, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return {name: value.encode("utf-8") for name, value in json.loads(result.stdout).items()}


def build_public(root, entries, *, check):
    public, pages = public_contents(entries)
    groups = navigation(root)
    paths = [p[0] for g in groups for p in g["pages"]]
    if len(paths) != len(set(paths)) or set(paths) != {p["path"] for p in pages}:
        raise ValueError("Documentation navigation differs from public Markdown pages")
    public["llms.txt"] = ai_index(
        groups,
        json.loads(entries["RELEASE.json"]),
        {p["path"]: p["markdown_path"] for p in pages},
        schema="openapi.json",
        example="examples/python/notify_bridge.py",
        rules=[
            (name, markdown_title(content, name))
            for name, content in public.items()
            if name.startswith("skill/") and name.endswith(".md")
        ],
    )
    digest = hashlib.sha256()
    inputs = {
        **public,
        "render-input.json": json.dumps(pages, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        **{
            name: (root / name).read_text(encoding="utf-8").encode("utf-8")
            for name in ("frontend/render-docs.mjs", "frontend/src/shared/theme.css")
        },
    }
    for asset in sorted((root / "frontend/docs").iterdir()):
        if asset.is_symlink() or not asset.is_file():
            raise ValueError("Invalid documentation build asset")
        inputs[asset.relative_to(root).as_posix()] = asset.read_bytes().replace(b"\r\n", b"\n")
    for name, value in sorted(inputs.items()):
        digest.update(name.encode() + b"\0" + value + b"\0")
    expected_rendered = {page["path"] for page in pages} | {
        "style.css",
        "script.js",
        "search-index.json",
    }
    output = root / "server/src/wechat_bridge/web/admin/public-docs.zip"
    if check:
        try:
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                manifest = json.loads(archive.read("_build.json"))
                if (
                    len(names) != len(set(names))
                    or set(names) != set(public) | expected_rendered | {"_build.json"}
                    or manifest["inputs_sha256"] != digest.hexdigest()
                    or set(manifest["outputs"]) != expected_rendered
                    or any(archive.read(n) != b for n, b in public.items())
                    or any(
                        hashlib.sha256(archive.read(n)).hexdigest() != h
                        for n, h in manifest["outputs"].items()
                    )
                ):
                    raise ValueError("stale")
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            raise SystemExit(
                "Stale public documentation; run python server/scripts/build_developer_kit.py"
            ) from None
        return
    rendered = render_public(root, pages, json.loads(entries["RELEASE.json"]))
    if set(rendered) != expected_rendered:
        raise ValueError("Public renderer returned unexpected files")
    public.update(rendered)
    public["_build.json"] = json.dumps(
        dict(
            inputs_sha256=digest.hexdigest(),
            outputs={n: hashlib.sha256(v).hexdigest() for n, v in rendered.items()},
        ),
        sort_keys=True,
    ).encode()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(public.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, value)


def contents(root):
    import sys

    sys.path.insert(0, str(ROOT / "mcp-plugin/tools"))
    from package_checks import portable_markdown, release_metadata

    entries = {"START-HERE.md": INTRO.encode("utf-8")}
    for name in FILES:
        path = root / name
        if path.is_symlink():
            raise ValueError("Symlinks are not developer kit inputs: " + name)
        content = path.read_text(encoding="utf-8")
        if path.suffix == ".svg":
            validate_diagram(content)
        if path.suffix == ".md":
            content = portable_markdown(content, name, set(FILES))
        entries[name] = content.encode("utf-8")
    version = release_metadata(root / "mcp-plugin", entries, scope="developer-docs")
    targets = {
        name.removeprefix("docs/")[:-3] + ".html": name for name in FILES if name.endswith(".md")
    }
    targets["operations/ADMIN.html"] = "docs/product-v3/OPERATIONS.md"
    targets["index.html"] = "docs/integration/README.md"
    entries["llms.txt"] = ai_index(
        navigation(root),
        version,
        targets,
        schema="server/openapi.json",
        example="examples/python/notify_bridge.py",
        rules=[
            (name, markdown_title(value, name))
            for name, value in entries.items()
            if name.startswith(SKILL_PREFIX) and name.endswith(".md")
        ],
    )
    release = release_metadata(root / "mcp-plugin", entries, scope="developer-docs")
    entries["RELEASE.json"] = json.dumps(release, ensure_ascii=False, indent=2).encode("utf-8")
    docs = {key: (root / path).read_text(encoding="utf-8") for key, path in DOCS.items()}
    docs.update(_sources=DOCS, _release=release)
    return entries, json.dumps(docs, ensure_ascii=False).encode("utf-8")


def build(root=ROOT, *, check=False):
    entries, docs = contents(root)
    out = root / "server/src/wechat_bridge/web/admin"
    if check:
        stale = []
        try:
            with zipfile.ZipFile(out / "developer-kit.zip") as archive:
                names = archive.namelist()
                if len(names) != len(set(names)) or set(names) != set(entries):
                    stale.append("developer-kit.zip member list")
                elif any(archive.read(name) != content for name, content in entries.items()):
                    stale.append("developer-kit.zip content")
        except (OSError, ValueError, zipfile.BadZipFile, KeyError):
            stale.append("developer-kit.zip unavailable or invalid")
        if (
            not (out / "developer-docs.json").is_file()
            or (out / "developer-docs.json").read_bytes() != docs
        ):
            stale.append("developer-docs.json")
        if stale:
            raise SystemExit(
                "Stale developer assets: "
                + ", ".join(stale)
                + "; run python server/scripts/build_developer_kit.py"
            )
        build_public(root, entries, check=True)
        return
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out / "developer-kit.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    (out / "developer-docs.json").write_bytes(docs)
    build_public(root, entries, check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from build_api_reference import build as build_reference

    build_reference(check=args.check)
    build(check=args.check)
    from build_onboarding_assets import build as build_onboarding

    build_onboarding(check=args.check)
    print("Developer assets: " + ("PASS" if args.check else "built"))
