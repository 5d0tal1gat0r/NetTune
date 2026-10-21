"""Who may reach the dashboard, and who sees the technical numbers.

There is no sign-in. The page is reachable from the centre's LAN and from the
tailnet and from nowhere else, and within those networks it opens. Being on
the centre's network is the permission, exactly as it already is for the scan
share beside it: the colleague opens a bookmark and starts working, and
nothing about the tool can lock him out on a morning when scans are waiting.

The two views are still told apart, without an interface for it. The author
reaches the Pi over Tailscale and the colleague over the LAN, so spend, model
and service state are rendered for one address range and simply are not there
for the other. That separates the views; it does not defend the numbers
against somebody determined on the LAN, and is not meant to.
"""

import hmac
import ipaddress
import os
import secrets
import socket

# The same two networks Samba was given, plus loopback for the Pi itself.
ALLOWED_NETWORKS = ("192.168.50.0/24", "100.64.0.0/10", "127.0.0.0/8")

# Tailscale's range. The author arrives this way; the colleague does not.
ADVANCED_NETWORKS = ("100.64.0.0/10",)

_TOKEN_BYTES = 24


def _within(address: str, networks: tuple[str, ...]) -> bool:
    try:
        parsed = ipaddress.ip_address((address or "").strip())
    except ValueError:
        return False
    return any(parsed in ipaddress.ip_network(net) for net in networks)


def is_allowed(address: str) -> bool:
    """True when a request from *address* may be served at all."""
    return _within(address, ALLOWED_NETWORKS)


def sees_advanced(address: str) -> bool:
    """True when *address* is offered the technical numbers."""
    return _within(address, ADVANCED_NETWORKS)


def _hostname(host_header: str) -> str:
    """The address a Host header names, stripped of an optional port.

    A bracketed IPv6 literal (``[::1]:8080``) carries its own colons, so the
    port is only split off outside the brackets; anything else with more
    than one colon is left alone rather than mangled.
    """
    header = host_header.strip()
    if header.startswith("["):
        return header[1:header.index("]")] if "]" in header else header
    if header.count(":") == 1:
        return header.split(":", 1)[0]
    return header


def own_names() -> set[str]:
    """The names this dashboard answers to, besides its addresses.

    The Pi's mDNS name (raspberrypi.local), which the bookmark and the email
    link use so they survive the router handing out another address, and any
    listed in DASHBOARD_HOSTNAMES. A .local name exists only on the local
    network -- no site can own one in public DNS -- so it cannot be the
    "other domain" of a rebinding attack.
    """
    names = {f"{socket.gethostname()}.local".lower()}
    extra = os.getenv("DASHBOARD_HOSTNAMES", "")
    names.update(name.strip().lower() for name in extra.split(",") if name.strip())
    return names


def is_allowed_host(host_header: str | None) -> bool:
    """True when a request's declared destination is one this dashboard
    actually answers to.

    A CSRF token stops a cross-site form post, but not DNS rebinding: a
    browser that has resolved some other domain to this Pi's LAN address
    treats a page served from it as same-origin, so a script there could GET
    /mes, read the token out of the page, and POST it straight back with a
    Host header naming that same other domain. That domain is never in
    ALLOWED_NETWORKS, so checking the Host header against the very same
    allowlist the client's address is checked against closes the gap without
    a second list to keep in step. The one addition is the Pi's own names
    (own_names), which no outside domain can be.
    """
    if not host_header:
        return False
    hostname = _hostname(host_header).lower()
    if hostname == "localhost" or hostname in own_names():
        return True
    return _within(hostname, ALLOWED_NETWORKS)


def new_token() -> str:
    """A CSRF token for one page.

    Without one, a page on another site could make a browser already on the
    LAN rewrite the memoria, which is precisely what no login leaves open.
    """
    return secrets.token_urlsafe(_TOKEN_BYTES)


def token_matches(expected: str, given: str | None) -> bool:
    """Compare in constant time, refusing an empty expectation."""
    if not expected or not given:
        return False
    return hmac.compare_digest(expected, given)
