"""Stable service errors, independent of a messaging platform."""


class BridgeError(Exception):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason
        super().__init__(reason)
