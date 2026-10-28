"""Production entry point: gunicorn pkmrp.web.wsgi:app.

Adds what only a deployed copy needs -- the Caddy path prefix (/pk-mrp) and
PK sign-in (pk_access, shared from pk-server-manager) -- so create_app()
stays plain for tests.
"""

import logging
import os

from werkzeug.middleware.proxy_fix import ProxyFix

from .app import create_app

log = logging.getLogger("pkmrp.web")


class PrefixMiddleware:
    """Serve under the prefix Caddy keeps on the path (X-Script-Name)."""

    def __init__(self, wsgi_app, prefix=""):
        self.app = wsgi_app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        prefix = self.prefix or environ.get("HTTP_X_SCRIPT_NAME", "")
        if prefix:
            path = environ.get("PATH_INFO", "")
            if path.startswith(prefix):
                environ["PATH_INFO"] = path[len(prefix) :] or "/"
            environ["SCRIPT_NAME"] = prefix
        return self.app(environ, start_response)


app = create_app()
try:
    from pk_access import init_flask_access

    # A grant is required: shadow-mode buys are for the planning team, not
    # company-wide. Grants are made in Server Manager's permissions page.
    init_flask_access(app, app_key="pk-mrp")
except ImportError:
    log.warning("pk_access not available -- running without access control")

app.wsgi_app = PrefixMiddleware(app.wsgi_app, os.environ.get("APP_PREFIX", ""))
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
