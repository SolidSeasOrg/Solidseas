"""No test reaches a network.

:func:`no_outbound_connections` makes any connection or name lookup to anything
but this machine's loopback fail with :class:`OutboundConnection` (an
``AssertionError``, so code that handles network errors cannot swallow it as
one) and records it. ``conftest.py`` keeps it on for the whole run, and the
service's test modules also use it module by module (``outbound_guard``).

It guards this process only: a worker, the service or the command line started
as a child process of a test is not covered, and its own code is what keeps it
off the network.
"""

import contextlib
import ipaddress
import socket

import pytest


class OutboundConnection(AssertionError):
    """Something in this process tried to reach a host other than loopback."""


_LOOPBACK_NAMES = {"localhost"}


def _is_loopback(host) -> bool:
    if host is None or host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(str(host).split("%", 1)[0]).is_loopback
    except ValueError:
        return False


@contextlib.contextmanager
def no_outbound_connections():
    """While active, ``connect``, ``connect_ex`` and ``getaddrinfo`` to any host but
    loopback raise :class:`OutboundConnection` and are recorded in the list yielded."""
    attempts: list[str] = []

    def check(address) -> None:
        if not isinstance(address, tuple):  # an AF_UNIX path: local by definition
            return
        if not _is_loopback(address[0]):
            attempts.append(str(address[0]))
            raise OutboundConnection(f"an outbound connection to {address[0]!r} was attempted")

    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def connect(self, address):
        check(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        check(address)
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if not _is_loopback(host.decode() if isinstance(host, bytes) else host):
            attempts.append(str(host))
            raise OutboundConnection(f"a name lookup of {host!r} was attempted")
        return real_getaddrinfo(host, *args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(socket.socket, "connect", connect)
        mp.setattr(socket.socket, "connect_ex", connect_ex)
        mp.setattr(socket, "getaddrinfo", getaddrinfo)
        yield attempts
