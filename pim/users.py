"""Named users with a role and jurisdictions. Keys are stored as scrypt
hashes. This is a stand-in for a department identity provider (SSO with MFA);
production should map an upstream-verified identity to security.identity
instead. Users come from the PIM_USERS environment variable or the admin
command, never from a form field or request header.

PIM_USERS format: name:role:JUR1|JUR2:key;name2:role:JUR:key2
"""
import hashlib
import hmac
import os
import secrets
from . import workflow


def _hash(key, salt):
    return hashlib.scrypt(key.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1).hex()


def create(conn, username, role, key, jurisdictions=("NA",)):
    if role not in workflow.ROLES:
        raise ValueError("unknown role")
    if not username or len(key) < 8:
        raise ValueError("username required and key must be at least 8 characters")
    salt = secrets.token_hex(16)
    conn.execute("INSERT OR REPLACE INTO users(username,role,salt,key_hash,active,jurisdictions) VALUES(?,?,?,?,1,?)",
                 (username, role, salt, _hash(key, salt), "|".join(jurisdictions)))


def authenticate(conn, username, key):
    r = conn.execute("SELECT * FROM users WHERE username=? AND active=1", (username or "",)).fetchone()
    salt = r["salt"] if r else "00" * 16
    ok = hmac.compare_digest(_hash(key or "", salt), r["key_hash"] if r else "0" * 128)
    if not (r and ok):
        return None
    return workflow.Actor(r["username"], r["role"], tuple(filter(None, (r["jurisdictions"] or "NA").split("|"))))


def bootstrap_from_env(conn):
    spec = os.environ.get("PIM_USERS", "")
    n = 0
    for item in filter(None, (x.strip() for x in spec.split(";"))):
        name, role, juris, key = item.split(":", 3)
        have = conn.execute("SELECT 1 FROM users WHERE username=?", (name,)).fetchone()
        if not have:
            create(conn, name, role, key, tuple(juris.split("|")))
            n += 1
    conn.commit()
    return n
