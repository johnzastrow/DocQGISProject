# SPDX-License-Identifier: GPL-2.0-or-later
"""Credential redaction for data-source URIs, decoded URI parts and free text.

Pure Python (no QGIS) so it can be unit-tested against a corpus. Conservative by design:
it prefers redacting a harmless value (a user name, a URL `key=`) over leaking a secret.

Covered shapes:
- QgsDataSourceUri style:   host=h user='bob' password='x y' sslmode=disable  # pragma: allowlist secret
- OGR/GDAL strings:         PG:dbname=gis password=x,  MSSQL:server=s;UID=u;PWD={a;b}
- URL query parameters:     https://h/{z}/{x}/{y}.png?api_key=abc&token=def
- URL user information:     https://user:pass@host/path  # pragma: allowlist secret
- Percent-encoded URLs nested in a WMS/XYZ URI: url=https%3A%2F%2Fh%2Fwms%3Fkey%3Dabc
- HTTP headers in WMS URIs: http-header:Authorization=Bearer abc
- Decoded dicts from QgsProviderRegistry.decodeUri (password, username, authcfg, url, ...)

Redacted values become explicit placeholders, never silently dropped:
text -> "[REDACTED:password]", dict values -> {"redacted": "password"}.
"""

import re
from collections import Counter
from urllib.parse import quote, unquote

PLACEHOLDER = "[REDACTED:{kind}]"


def _by_kind(table):
    """Invert {kind: (names...)} into {name: kind}. Tables are written kind-first for reading."""
    return {name: kind for kind, names in table.items() for name in names}


# Keys that are secret in any context, grouped by the kind reported.
_ALWAYS = _by_kind({
    "password": ("password", "passwd", "pass", "pwd"),
    "user": ("user", "username", "uid", "login", "user_id"),
    "secret": ("secret", "client_secret", "secret_key", "private_key"),
    "token": ("token", "access_token", "refresh_token", "id_token", "auth_token", "sas_token", "bearer"),
    "api_key": ("api_key", "apikey", "x_api_key", "access_key", "subscription_key"),
    "auth_config": ("authcfg",),
    "authorization": ("authorization",),
    "signature": ("signature", "sig"),
    "session": ("session", "sessionid"),
    "credential": ("credential", "credentials"),
})
# Keys that are secret only inside a URL query string. In a QgsDataSourceUri `key='id'`
# names the primary-key column, which must stay readable.
_URL_ONLY = _by_kind({
    "key": ("key", "code", "app_id", "appid", "app_code", "client_id"),
    "authorization": ("auth",),
})
# Variable / custom-property NAMES that suggest the value is secret. Matched on whole words of
# the normalised name (db_password, mapboxToken -> mapbox_token), so "author" is not "auth".
_SECRET_WORDS = _by_kind({
    "password": ("password", "passwd", "pwd", "pass"),
    "secret": ("secret",),
    "token": ("token", "bearer", "sas"),
    "api_key": ("apikey",),
    "credential": ("credential", "credentials"),
    "authorization": ("auth", "authorization"),
    "auth_config": ("authcfg",),
})
_SECRET_PAIRS = {("api", "key"): "api_key", ("access", "key"): "api_key", ("private", "key"): "secret"}


def secret_name_kind(name):
    """Kind of secret a variable/property NAME suggests, or None. Whole-word match."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name))
    words = [w for w in re.split(r"[^A-Za-z0-9]+", s.lower()) if w]
    for a, b in zip(words, words[1:]):
        if (a, b) in _SECRET_PAIRS:
            return _SECRET_PAIRS[(a, b)]
    for w in words:
        if w in _SECRET_WORDS:
            return _SECRET_WORDS[w]
    return None


_USERINFO_RE = re.compile(r"(?P<scheme>\b[A-Za-z][A-Za-z0-9+.\-]*://)(?P<userinfo>[^/?#@\s'\"]+)@")
_PAIR_RE = re.compile(
    r"""(?P<pre>^|[\s;&?|,(])
        (?P<key>[A-Za-z_][\w.\-:]*)
        (?P<eq>\s*=\s*)
        (?P<val>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|\{[^}]*\}|[^\s;&|,)'"]*)""",
    re.VERBOSE,
)


def _norm(key):
    """Normalise a key for lookup: last segment after ':' (http-header:X), lower, '-' -> '_'."""
    return key.rsplit(":", 1)[-1].strip().lower().replace("-", "_")


def sensitive_kind(key, url_context=False):
    """Return the redaction kind for a parameter name, or None if it is not sensitive."""
    k = _norm(key)
    if k in _ALWAYS:
        return _ALWAYS[k]
    if url_context and k in _URL_ONLY:
        return _URL_ONLY[k]
    # HTTP headers carrying credentials (http-header:X-Auth-Token=...).
    if key.lower().startswith("http-header:") and secret_name_kind(k):
        return "authorization"
    return None


def _strip_quotes(val):
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
        return val[0], val[1:-1]
    if len(val) >= 2 and val[0] == "{" and val[-1] == "}":
        return "{", val[1:-1]
    return "", val


def _requote(quote_char, inner):
    if quote_char == "{":
        return "{" + inner + "}"
    return f"{quote_char}{inner}{quote_char}"


def redact_text(text, _depth=0):
    """Redact credentials in a URI or free text. Returns (redacted_text, Counter of kinds)."""
    kinds = Counter()
    if not text or not isinstance(text, str):
        return text, kinds

    def userinfo(m):
        kinds["userinfo"] += 1
        return m.group("scheme") + PLACEHOLDER.format(kind="userinfo") + "@"

    out = _USERINFO_RE.sub(userinfo, text)

    def pair(m):
        key, val = m.group("key"), m.group("val")
        url_context = m.group("pre") in ("?", "&")
        kind = sensitive_kind(key, url_context)
        q, inner = _strip_quotes(val)
        if kind:
            if not inner:
                return m.group(0)  # empty value: nothing to hide
            kinds[kind] += 1
            return m.group("pre") + key + m.group("eq") + _requote(q, PLACEHOLDER.format(kind=kind))
        # Not sensitive itself, but the value may be a URL holding secrets (XYZ/WMS url=...),
        # either plain (url=https://h/t.png?api_key=x) or percent-encoded (...%3Fapi_key%3Dx).
        if _depth < 3 and any(c in inner for c in "=?@%"):
            red, sub = redact_text(inner, _depth + 1)
            if sub:
                kinds.update(sub)
                return m.group("pre") + key + m.group("eq") + _requote(q, red)
            decoded = unquote(inner)
            if decoded != inner:
                red, sub = redact_text(decoded, _depth + 1)
                if sub:
                    kinds.update(sub)
                    return m.group("pre") + key + m.group("eq") + _requote(q, quote(red, safe=":/{}[]"))
        return m.group(0)

    # A pair preceded by '?' or '&' is in URL-query context, where `key=` is a secret.
    out = _PAIR_RE.sub(pair, out)
    return out, kinds


def redact_mapping(data, _depth=0):
    """Redact a decoded URI dict (or nested list/dict). Returns (new_object, Counter of kinds)."""
    kinds = Counter()
    if _depth > 5:
        return data, kinds
    if isinstance(data, dict):
        out = {}
        for key, value in data.items():
            kind = sensitive_kind(str(key)) if isinstance(key, str) else None
            if kind and value not in (None, "", [], {}):
                kinds[kind] += 1
                out[key] = {"redacted": kind}
                continue
            out[key], sub = redact_mapping(value, _depth + 1)
            kinds.update(sub)
        return out, kinds
    if isinstance(data, (list, tuple)):
        items = []
        for value in data:
            red, sub = redact_mapping(value, _depth + 1)
            items.append(red)
            kinds.update(sub)
        return items, kinds
    if isinstance(data, str):
        return redact_text(data)
    return data, kinds


def redact_named_value(name, value):
    """Redact a named value (project variable, custom property).

    The whole value is hidden when the name suggests a secret; otherwise the value text is
    scanned like a URI. Returns (value_or_placeholder_dict, Counter).
    """
    kinds = Counter()
    if value in (None, ""):
        return value, kinds
    kind = sensitive_kind(str(name)) or secret_name_kind(name)
    if kind:
        kinds[kind] += 1
        return {"redacted": kind}, kinds
    if isinstance(value, str):
        return redact_text(value)
    return value, kinds
