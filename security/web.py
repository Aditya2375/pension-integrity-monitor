"""Framework controls for the review portal, not an identity provider."""
import ipaddress
import secrets
from flask import abort, request, session

SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})

def csrf_token():
    token = session.get('_csrf')
    if not isinstance(token, str) or len(token) != 64:
        token = secrets.token_hex(32)
        session['_csrf'] = token
    return token

def install_csrf(app):
    """Call once. Add {{ csrf_token() }} hidden input to EVERY POST form.

    Includes login and public appeals. Never exempt a mutation to fix a broken
    client. Rotate by clearing the session after sign-in/sign-out.
    """
    app.jinja_env.globals['csrf_token'] = csrf_token

    @app.before_request
    def check_csrf():
        if request.method not in SAFE_METHODS:
            expected = session.get('_csrf')
            supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
            if (not isinstance(expected, str) or not isinstance(supplied, str)
                    or len(supplied) != 64 or not secrets.compare_digest(expected, supplied)):
                abort(400, description='Invalid or missing form token. Reload the form and retry.')

    @app.after_request
    def private_headers(response):
        # All portal pages may contain identifiers or bearer appeal tokens.
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Pragma'] = 'no-cache'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response

def client_ip(remote_addr, forwarded_for=None, trusted_proxy_cidrs=()):
    """Walk right-to-left ONLY when the socket peer is an explicitly trusted proxy.

    The edge must overwrite untrusted forwarding headers. This does not trust
    X-Forwarded-Proto or user identity headers. Invalid input fails closed to
    the socket peer; deployment must configure its real proxy address ranges.
    """
    try:
        peer = ipaddress.ip_address(remote_addr)
        networks = tuple(ipaddress.ip_network(c) for c in trusted_proxy_cidrs)
    except ValueError:
        return remote_addr or 'unknown'
    trusted = lambda ip: any(ip in net for net in networks)
    if not trusted(peer) or not forwarded_for:
        return str(peer)
    values = forwarded_for.split(',')
    if len(values) > 16:
        return str(peer)
    try:
        chain = [ipaddress.ip_address(v.strip()) for v in values] + [peer]
    except ValueError:
        return str(peer)
    for ip in reversed(chain):
        if not trusted(ip):
            return str(ip)
    return str(chain[0])

def csv_cell(value):
    """Quote formula-like text before spreadsheet export, including leading whitespace."""
    text = '' if value is None else str(value)
    if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
        return "'" + text
    return text
