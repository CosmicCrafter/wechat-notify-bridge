"""Build the self-contained stdio plugin without credentials or dependencies."""
import argparse
from pathlib import Path
import zipfile

from package_checks import check, public_files


def build(output):
    source = Path(__file__).resolve().parents[1]
    manifest = check(source)
    output = Path(output).resolve()
    if output.is_relative_to(source):
        raise ValueError('Write the archive outside the plugin source directory')
    names = ['plugin.json', 'mcp.json', '.codex-plugin/plugin.json', '.mcp.json',
             'requirements.txt', 'README.md', 'DESKTOP-WAKE.md']
    files = [source/name for name in names]
    for directory, suffixes in [('server', {'.py'}), ('tools', {'.py'}),
                                ('skills', {'.md', '.yaml'}), ('examples', {'.json'})]:
        files.extend(public_files(source/directory, suffixes))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            if path.is_symlink():
                raise ValueError('Symlinks are not allowed')
            info = zipfile.ZipInfo(manifest['name']+'/'+path.relative_to(source).as_posix(), (2026,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    print(build(parser.parse_args().output))
