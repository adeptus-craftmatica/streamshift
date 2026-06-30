from __future__ import annotations

import ssl


def make_ssl_context() -> ssl.SSLContext:
    """Return an SSL context backed by certifi's CA bundle.

    On macOS, Python's bundled ssl module doesn't use the system keychain,
    so HTTPS requests fail with CERTIFICATE_VERIFY_FAILED.  certifi ships its
    own up-to-date CA bundle that works everywhere.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()
