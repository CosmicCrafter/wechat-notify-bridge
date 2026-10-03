"""Build a reproducible source archive using an explicit public-file allowlist."""
import argparse
from pathlib import Path
import zipfile

from sync_shared import ROOT
from check_project import check

DIRECTORIES = ('docs', 'scripts', 'server/src/wechat_bridge', 'server/tests', 'server/scripts',
               'server/deploy', 'mcp-plugin/server', 'mcp-plugin/tests',
               'mcp-plugin/tools', 'mcp-plugin/skills', 'mcp-plugin/examples',
               'mcp-plugin/.codex-plugin')
SUFFIXES = {'.py', '.md', '.json', '.yaml', '.yml', '.toml', '.html', '.css', '.js', '.txt', '.conf'}
TOP_FILES = ('README.md', '.gitignore', '.gitattributes', '.github/workflows/test.yml', 'pytest.ini', 'server/README.md',
             'server/pyproject.toml', 'server/requirements.txt', 'server/requirements-dev.txt',
             'server/Dockerfile', 'server/.dockerignore', 'server/compose.yaml',
             'server/.env.example', 'server/openapi.json', 'mcp-plugin/README.md',
             'mcp-plugin/DESKTOP-WAKE.md', 'mcp-plugin/requirements.txt',
             'mcp-plugin/plugin.json', 'mcp-plugin/mcp.json', 'mcp-plugin/.mcp.json')


def build(output):
    check()
    files = {ROOT / name for name in TOP_FILES}
    for directory in DIRECTORIES:
        for path in (ROOT / directory).rglob('*'):
            relative = path.relative_to(ROOT)
            if (path.is_file() and not path.is_symlink() and path.suffix in SUFFIXES
                    and not any(part.startswith('.') or part == '__pycache__' for part in relative.parts
                                if part != '.codex-plugin')):
                files.add(path)
    output = Path(output).resolve()
    if output in files:
        raise ValueError('Output would overwrite a source file')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            if path.is_symlink():
                raise ValueError('Symlinks are not release inputs')
            info = zipfile.ZipInfo('wechat-notify-bridge/' + path.relative_to(ROOT).as_posix(),
                                   date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / 'dist/wechat-notify-bridge-source.zip'))
    print(build(parser.parse_args().output))
