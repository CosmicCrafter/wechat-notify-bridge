"""Feishu SHA-256 signature and AES-CBC envelope verification."""
import base64
import hashlib
import hmac
import json
import time

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from wechat_bridge.wechat.protocol import BridgeError


def verify(raw, headers, settings):
    try:
        envelope = json.loads(raw)
        if not isinstance(envelope, dict) or not isinstance(envelope.get('encrypt'), str):
            raise ValueError()
        data = base64.b64decode(envelope['encrypt'], validate=True)
        if len(data) < 32 or len(data) % 16:
            raise ValueError()
        key = hashlib.sha256(settings['encrypt_key'].encode()).digest()
        decryptor = Cipher(algorithms.AES(key), modes.CBC(data[:16])).decryptor()
        padded = decryptor.update(data[16:]) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        value = json.loads(unpadder.update(padded) + unpadder.finalize())
        if not isinstance(value, dict):
            raise ValueError()
        header = value.get('header') or {}
        token = header.get('token', value.get('token', ''))
        if not isinstance(token, str) or not hmac.compare_digest(token, settings['verification_token']):
            raise ValueError()
        # URL verification is authenticated by the encrypted envelope and token.
        if value.get('type') != 'url_verification':
            stamp = headers.get('x-lark-request-timestamp', '')
            nonce = headers.get('x-lark-request-nonce', '')
            signature = headers.get('x-lark-signature', '')
            if not stamp.isdigit() or abs(time.time() - int(stamp)) > 300 or not 1 <= len(nonce) <= 256:
                raise ValueError()
            expected = hashlib.sha256((stamp + nonce + settings['encrypt_key']).encode() + raw).hexdigest()
            if not hmac.compare_digest(expected, signature) or header.get('app_id') != settings['app_id']:
                raise ValueError()
        return value
    except (ValueError, TypeError, KeyError, AttributeError):
        raise BridgeError(401, 'invalid_feishu_callback') from None
