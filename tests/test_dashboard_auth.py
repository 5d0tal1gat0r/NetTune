"""Who may connect, who sees the technical numbers, and CSRF tokens.

There is no sign-in. Access is decided by the network the request comes from,
the same way the scan share beside it works, and the author's view is told
apart from the colleague's by the fact that he arrives over Tailscale.
"""

import pytest

from nettune.review.dashboard_auth import (
    is_allowed,
    new_token,
    sees_advanced,
    token_matches,
)


class TestWhoMayConnect:
    @pytest.mark.parametrize("address", [
        "192.168.50.37",      # the Pi's own LAN
        "192.168.50.41",      # the colleague's PC
        "100.64.0.10",   # the tailnet
        "100.64.0.10",
        "127.0.0.1",
    ])
    def test_the_two_networks_and_loopback_are_allowed(self, address):
        assert is_allowed(address)

    @pytest.mark.parametrize("address", [
        "8.8.8.8",
        "192.168.1.10",     # a different LAN
        "172.27.0.5",       # next subnet along
        "10.0.0.4",
        "",
        "not an address",
    ])
    def test_everything_else_is_refused(self, address):
        assert not is_allowed(address)


class TestWhoSeesAdvanced:
    def test_the_tailnet_sees_it(self):
        assert sees_advanced("100.64.0.10")

    @pytest.mark.parametrize("address", ["192.168.50.41", "127.0.0.1", "8.8.8.8"])
    def test_nobody_else_does(self, address):
        assert not sees_advanced(address)


class TestTokens:
    def test_a_token_matches_itself(self):
        token = new_token()
        assert token_matches(token, token)

    def test_two_tokens_differ(self):
        assert new_token() != new_token()

    def test_a_token_is_long_enough_to_be_unguessable(self):
        assert len(new_token()) >= 32

    @pytest.mark.parametrize("given", ["", "wrong", None])
    def test_anything_else_is_refused(self, given):
        assert not token_matches(new_token(), given)

    def test_an_empty_expected_token_never_matches(self):
        assert not token_matches("", "")


class TestTheNameItAnswersTo:
    """The bookmark and the email link say http://raspberrypi.local:8080, so
    they keep working when the router hands the Pi another address. The name
    is the Pi's own mDNS name: a hostile site can never own a .local name in
    public DNS, so accepting it does not reopen DNS rebinding."""

    @pytest.fixture(autouse=True)
    def named(self, monkeypatch):
        from nettune.review import dashboard_auth
        monkeypatch.setattr(dashboard_auth.socket, "gethostname", lambda: "RaspberryPi")
        monkeypatch.setenv("DASHBOARD_HOSTNAMES", "")

    @pytest.mark.parametrize("host", ["raspberrypi.local:8080", "raspberrypi.local",
                                      "RASPBERRYPI.LOCAL:8080", "192.168.50.37:8080",
                                      "localhost:8080"])
    def test_it_answers_to_its_own_name_and_addresses(self, host):
        from nettune.review.dashboard_auth import is_allowed_host
        assert is_allowed_host(host)

    @pytest.mark.parametrize("host", ["evil.example:8080", "raspberrypi.local.evil.example",
                                      "raspberrypi", "otherpi.local:8080", "8.8.8.8", ""])
    def test_anything_else_is_refused(self, host):
        from nettune.review.dashboard_auth import is_allowed_host
        assert not is_allowed_host(host)

    def test_more_names_can_be_given(self, monkeypatch):
        from nettune.review.dashboard_auth import is_allowed_host
        monkeypatch.setenv("DASHBOARD_HOSTNAMES", "nettune.local, Dashboard.Station")
        assert is_allowed_host("nettune.local:8080")
        assert is_allowed_host("dashboard.station")
        assert not is_allowed_host("evil.example")
