"""Synchronize portable plugin copies from their canonical project sources."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPIES = (
    ('server/src/wechat_bridge/mcp/errors.py', 'mcp-plugin/server/api_errors.py'),
    ('server/src/wechat_bridge/mcp/tools.py', 'mcp-plugin/server/toolkit.py'),
    ('docs/wechat-markdown/微信Markdown排版指南.md',
     'mcp-plugin/skills/wechat-notify/references/wechat-markdown.md'),
)


def sync(check=False):
    stale = []
    for source, destination in COPIES:
        content = (ROOT / source).read_bytes()
        target = ROOT / destination
        if not target.exists() or target.read_bytes() != content:
            stale.append(destination)
            if not check:
                target.write_bytes(content)
    if check and stale:
        raise SystemExit('Shared copies differ; run python scripts/sync_shared.py: ' + ', '.join(stale))
    return stale


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    sync(args.check)
    print('Shared files are synchronized.')
