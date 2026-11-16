"""Optional HTTPS guest origin and short-lived TURN credentials; never opens ports."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import urlsplit


class GreenroomNetwork:
    def __init__(self, public_origin="", turn_urls=(), turn_secret="", *, clock=time.time):
        self.public_origin, self.turn_urls, self._secret, self.clock = "", (), "", clock
        if public_origin:
            parsed = urlsplit(public_origin)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or len(public_origin) > 300):
                raise ValueError("invalid_guest_https_origin")
            self.public_origin = public_origin.rstrip("/")
        if not isinstance(turn_urls, (list, tuple)) or len(turn_urls) > 4:
            raise ValueError("invalid_guest_relay")
        if any(not isinstance(url, str) or len(url) > 300 or not re.fullmatch(r"turns?:[A-Za-z0-9.\-\[\]:]+(?:\?transport=(?:tcp|udp))?", url) for url in turn_urls):
            raise ValueError("invalid_guest_relay")
        if turn_urls and (not isinstance(turn_secret, str) or not 20 <= len(turn_secret) <= 512):
            raise ValueError("guest_relay_secret_required")
        self.turn_urls, self._secret = tuple(turn_urls), turn_secret

    @classmethod
    def from_environment(cls):
        # Host deployment settings only. Defaults retain local-only guest testing.
        return cls(os.getenv("PRODUCER_GUEST_HTTPS_ORIGIN", ""),
                   json.loads(os.getenv("PRODUCER_GUEST_TURN_URLS", "[]")),
                   os.getenv("PRODUCER_GUEST_TURN_SECRET", ""))

    def ice_servers(self):
        if not self.turn_urls:
            return []
        username = str(int(self.clock()) + 900)
        credential = base64.b64encode(hmac.new(self._secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
        return [{"urls": list(self.turn_urls), "username": username, "credential": credential}]
