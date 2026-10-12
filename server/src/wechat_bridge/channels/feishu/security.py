"""Feishu SHA-256 signature and AES-CBC envelope verification."""

import base64
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import datetime

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from wechat_bridge.core.errors import BridgeError


def request_time(stamp):
    """Parse a signed timestamp without changing the bytes used for its signature."""
    if stamp.isascii() and stamp.isdigit() and len(stamp) in (10, 13):
        return int(stamp) / (1000 if len(stamp) == 13 else 1), "epoch"
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))? "
        r"([+-]\d{4}) [A-Za-z]{1,10}(?: m=[+-]\d{1,16}(?:\.\d{1,9})?)?",
        stamp,
        flags=re.ASCII,
    )
    if not match:
        raise ValueError("unsupported_timestamp")
    moment = datetime.strptime(match[1] + " " + match[3], "%Y-%m-%d %H:%M:%S %z")
    return moment.timestamp() + float("0." + (match[2] or "0")), "go_datetime"


def verify(raw, headers, settings):
    stage = "envelope"
    try:
        envelope = json.loads(raw)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("encrypt"), str):
            raise ValueError()
        stage = "decrypt"
        data = base64.b64decode(envelope["encrypt"], validate=True)
        if len(data) < 32 or len(data) % 16:
            raise ValueError()
        key = hashlib.sha256(settings["encrypt_key"].encode()).digest()
        decryptor = Cipher(algorithms.AES(key), modes.CBC(data[:16])).decryptor()
        padded = decryptor.update(data[16:]) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        value = json.loads(unpadder.update(padded) + unpadder.finalize())
        if not isinstance(value, dict):
            raise ValueError()
        stage = "token"
        header = value.get("header") or {}
        token = header.get("token", value.get("token", ""))
        if not isinstance(token, str) or not hmac.compare_digest(
            token, settings["verification_token"]
        ):
            raise ValueError()
        # URL verification is authenticated by the encrypted envelope and token.
        if value.get("type") != "url_verification":
            stage = "timestamp_nonce"
            stamp = headers.get("x-lark-request-timestamp", "")
            nonce = headers.get("x-lark-request-nonce", "")
            signature = headers.get("x-lark-signature", "")
            if not 1 <= len(stamp) <= 128 or not 1 <= len(nonce) <= 256:
                raise ValueError()
            expected = hashlib.sha256(
                (stamp + nonce + settings["encrypt_key"]).encode() + raw
            ).hexdigest()
            stage = "signature"
            if not hmac.compare_digest(expected, signature):
                raise ValueError()
            stage = "app_id"
            if header.get("app_id") != settings["app_id"]:
                raise ValueError()
            stage = "timestamp_format"
            seconds, stamp_format = request_time(stamp)
            stage = "timestamp_expired"
            if abs(time.time() - seconds) > 300:
                raise ValueError()
            if header.get("event_type") == "card.action.trigger":
                logging.getLogger(__name__).info(
                    "feishu_card_signature_verified timestamp_format=%s", stamp_format
                )
        return value
    except (ValueError, TypeError, KeyError, AttributeError):
        if stage == "timestamp_format":
            # Reached only after token, signature and app identity were verified.
            logging.getLogger(__name__).warning(
                "feishu_signed_timestamp_unrecognized value=%r", stamp
            )
        # Fixed stage names only: never log bodies, credentials or header values.
        logging.getLogger(__name__).warning("feishu_callback_rejected stage=%s", stage)
        raise BridgeError(401, "invalid_feishu_callback") from None
