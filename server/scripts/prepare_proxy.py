"""Create private Mihomo/controller configuration; no subscriptions or secrets are printed."""
import argparse
import copy
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

import yaml


def prepare(output, controller_url, controller_bind, import_config=None, import_callback=None):
    p = urlsplit(controller_url)
    if p.scheme != 'http' or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError('Use an internal controller HTTP URL')
    if bool(import_config) != bool(import_callback):
        raise ValueError('Provide both import files')
    root = Path(output).resolve()
    if root.exists():
        raise FileExistsError('Output exists; preserve the existing credentials')
    controller_secret = secrets.token_urlsafe(40)
    if import_config:
        base = yaml.safe_load(Path(import_config).read_text(encoding='utf-8'))
        callback = json.loads(Path(import_callback).read_text(encoding='utf-8'))
    else:
        password = secrets.token_urlsafe(40)
        base = {'port': 7890, 'allow-lan': True, 'bind-address': '0.0.0.0', 'mode': 'rule',
                'log-level': 'warning', 'ipv6': False, 'authentication': ['wechat:' + password],
                'proxies': [], 'rules': ['MATCH,REJECT']}
        callback = {'host': 'wechat-proxy', 'port': 7890, 'username': 'wechat', 'password': password,
                    'allowed_hosts': ['connectors.api.openai.com']}
    base = copy.deepcopy(base)
    base['external-controller'] = controller_bind
    base['secret'] = controller_secret
    control = {'controller_url': controller_url, 'controller_secret': controller_secret,
               'base_config': base, 'callback': callback, 'allowed_hosts': callback['allowed_hosts']}
    root.mkdir(parents=True, mode=0o700)
    (root/'runtime').mkdir(mode=0o700)
    for name, value in [('mihomo.json', base), ('callback-proxy.json', callback), ('proxy-control.json', control)]:
        fd = os.open(root/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='.private/proxy-bootstrap')
    parser.add_argument('--controller-url', default='http://wechat-proxy:9090')
    parser.add_argument('--controller-bind', default='0.0.0.0:9090')
    parser.add_argument('--import-config')
    parser.add_argument('--import-callback')
    args = parser.parse_args()
    result = prepare(args.output, args.controller_url, args.controller_bind, args.import_config, args.import_callback)
    print('Private proxy files prepared at ' + str(result))
