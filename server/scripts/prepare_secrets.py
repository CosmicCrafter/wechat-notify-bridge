"""Prepare a new server bootstrap and client credentials; no network requests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import urlsplit

from cryptography.fernet import Fernet

from wechat_bridge.wechat.protocol import validate_base
from wechat_bridge.storage.client_registry import client_name


def validate_public_url(base_url):
    parsed = urlsplit(base_url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment):
        raise ValueError('Use your public HTTPS API base URL')


def write_private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(value)


def prepare_admin(output, base_url):
    """Add web administration to an existing installation without rotating its keys."""
    validate_public_url(base_url)
    output = Path(output).resolve()
    private = output / 'secrets'
    if not (private / 'encryption.key').is_file() or not (private / 'clients.json').is_file():
        raise ValueError('Initialize server secrets first')
    if (private / 'admin.json').exists() or (output / 'admin').exists():
        raise FileExistsError('Administrator configuration already exists')
    (output / 'admin').mkdir(mode=0o700)
    key = secrets.token_urlsafe(40)
    write_private(output / 'admin' / 'admin.json', json.dumps({
        'admin_url': base_url.rstrip('/') + '/admin/', 'admin_key': key}, indent=2).encode())
    write_private(private / 'admin.json', json.dumps({
        'key_sha256': hashlib.sha256(key.encode()).hexdigest()}, indent=2).encode())
    return output


def prepare(credentials, output, base_url, clients):
    validate_public_url(base_url)
    clients = [client_name(name) for name in clients]
    if len(set(clients)) != len(clients):
        raise ValueError('Use distinct client names')
    if credentials is not None:
        for field in ('bot_token', 'user_id', 'context_token', 'base_url'):
            if not isinstance(credentials.get(field), str) or not credentials[field]:
                raise ValueError('Pairing credentials are incomplete')
        validate_base(credentials['base_url'])
    output = Path(output).resolve()
    # Never rotate or mix deployment keys on a retry.
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    private = output / 'secrets'
    client_dir = output / 'clients'
    private.mkdir(mode=0o700)
    client_dir.mkdir(mode=0o700)

    key = Fernet.generate_key()
    write_private(private / 'encryption.key', key)
    if credentials is not None:
        write_private(private / 'bootstrap.enc', Fernet(key).encrypt(
            json.dumps({'credentials': credentials, 'outgoing': {}}).encode()))
    registry = {}
    for name in clients:
        api_key = secrets.token_urlsafe(40)
        registry[name] = hashlib.sha256(api_key.encode()).hexdigest()
        write_private(client_dir / (name + '.json'), json.dumps({
            'base_url': base_url.rstrip('/'), 'api_key': api_key, 'caller': name}, indent=2).encode())
    write_private(private / 'clients.json', json.dumps(registry, indent=2).encode())
    prepare_admin(output, base_url)
    return output


def main():
    server = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--web-pairing', action='store_true', help='Start unbound; scan QR in the server web page')
    source.add_argument('--admin-only', action='store_true', help='Add administrator files to existing server secrets')
    source.add_argument('--credentials-json', type=Path, help='Existing private pairing JSON, never committed')
    source.add_argument('--pairing-dir', type=Path, default=server / '.private', help='Windows pairing output directory')
    parser.add_argument('--output', type=Path, default=server / '.private' / 'provisioned')
    parser.add_argument('--base-url', required=True, help='Your public HTTPS API URL, including /wechat')
    parser.add_argument('--clients', nargs='*', default=[], help='Optional initial clients; otherwise issue keys in WeChat or Admin')
    args = parser.parse_args()
    if args.admin_only:
        output = prepare_admin(args.output, args.base_url)
    elif args.credentials_json:
        credentials = json.loads(args.credentials_json.read_text(encoding='utf-8'))
        output = prepare(credentials, args.output, args.base_url, args.clients)
    elif args.web_pairing:
        output = prepare(None, args.output, args.base_url, args.clients)
    else:
        from pair_wechat import dpapi
        credentials = json.loads(dpapi((args.pairing_dir / 'wechat-credentials.dpapi').read_bytes(), decrypt=True))
        output = prepare(credentials, args.output, args.base_url, args.clients)
    print('Prepared server secrets and client configurations in: ' + str(output))
    print('Open the admin_url and use admin_key from the private admin/admin.json file.')
    print('No tokens printed. Keep this directory out of source control.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Parsing errors can contain credential contents; only reveal the exception type.
        print('Preparation failed: ' + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
