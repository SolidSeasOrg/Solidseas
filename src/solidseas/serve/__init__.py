"""``solidseas serve``: the read-only REST service (``docs/API.md`` section 8).

* :mod:`.server`: the HTTP server, its guards, routes and answers;
* :mod:`.query`: one query-parameter allowlist per route;
* :mod:`.paths`: a request path checked as text and found in the root's folder
  index, never joined into a path;
* :mod:`.tokens`: the bearer-token file and the service's identity key.

The Python API of this package is provisional until 0.2.0.
"""

from .server import (
    DEFAULT_PORT,
    ROUTES,
    ServeConfig,
    Server,
    check_bind,
    configure_logging,
    default_workers,
    run_until_signalled,
)
from .tokens import (
    IDENTITY_SCHEME,
    TokenChecker,
    create_identity_key_file,
    create_token_file,
    default_identity_key_file,
    default_token_file,
    ensure_identity_key,
    ensure_token_file,
    identity_proof,
    load_identity_key,
    load_tokens,
    parse_identity_address,
    proof_address,
)

__all__ = [
    "DEFAULT_PORT",
    "IDENTITY_SCHEME",
    "ROUTES",
    "ServeConfig",
    "Server",
    "TokenChecker",
    "check_bind",
    "configure_logging",
    "create_identity_key_file",
    "create_token_file",
    "default_identity_key_file",
    "default_token_file",
    "default_workers",
    "ensure_identity_key",
    "ensure_token_file",
    "identity_proof",
    "load_identity_key",
    "load_tokens",
    "parse_identity_address",
    "proof_address",
    "run_until_signalled",
]
