"""Check documentation links, shared copies and bundled vendor integrity."""
import hashlib
import json
import re
import subprocess
import sys

from sync_shared import ROOT, sync


def check():
    sync(check=True)
    subprocess.run([sys.executable, str(ROOT/'mcp-plugin/tools/package_checks.py')], check=True)
    ignored = {'.git', '.idea', '.pytest_cache', '.venv', '.private', '.data',
               '.secrets', 'build', 'dist', '__pycache__'}
    broken = []
    for file in ROOT.rglob('*.md'):
        if file.is_symlink() or any(part in ignored for part in file.relative_to(ROOT).parts):
            continue
        for target in re.findall(r'\]\(([^)]+)\)', file.read_text(encoding='utf-8')):
            if re.match(r'\w+:|#', target):
                continue
            path = target.split('#')[0]
            if path and not (file.parent / path).exists():
                broken.append(f'{file.relative_to(ROOT)}: {target}')
    if broken:
        raise SystemExit('Broken relative links:\n' + '\n'.join(broken))
    vendor = ROOT / 'server/src/wechat_bridge/web/vendor'
    for entry in json.loads((vendor / 'vendor-lock.json').read_text(encoding='utf-8')):
        path = vendor / entry['file']
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise SystemExit('Vendor checksum mismatch: ' + entry['file'])


if __name__ == '__main__':
    check()
    print('Documentation, shared files and vendor integrity: PASS')
