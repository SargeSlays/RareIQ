import base64
import hashlib
import hmac

import pytest

from rareiq.services.greenroom_network import GreenroomNetwork


def test_default_opens_no_remote_transport():
    network = GreenroomNetwork()
    assert network.public_origin == "" and network.ice_servers() == []


def test_relay_credentials_expire_and_do_not_expose_shared_secret():
    secret = "fixture-secret-not-real-123456"
    network = GreenroomNetwork("https://guest.example.test/", ["turns:relay.example.test:5349?transport=tcp"], secret, clock=lambda: 1000)
    result = network.ice_servers()[0]
    assert network.public_origin == "https://guest.example.test"
    assert result["username"] == "1900"
    assert result["credential"] == base64.b64encode(hmac.new(secret.encode(), b"1900", hashlib.sha1).digest()).decode()
    assert secret not in str(result)


@pytest.mark.parametrize("origin", ["http://guest.example.test", "https://user:pass@guest.example.test", "https://guest.example.test/path", "https://guest.example.test?token=x", "https://guest.example.test/#x"])
def test_only_https_origin_is_accepted(origin):
    with pytest.raises(ValueError):
        GreenroomNetwork(origin)


@pytest.mark.parametrize("urls,secret", [(["https://relay.example.test"], "x"*30), (["turn:relay.example.test"], ""), (["turn:user:pass@relay.example.test"], "x"*30), (["turn:host"]*5, "x"*30)])
def test_invalid_relay_settings_fail_closed(urls, secret):
    with pytest.raises(ValueError):
        GreenroomNetwork(turn_urls=urls, turn_secret=secret)
