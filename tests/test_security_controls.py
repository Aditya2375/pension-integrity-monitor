import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from flask import Flask
from security.web import install_csrf, csrf_token, client_ip, csv_cell
from security.identity import Principal, authorized, independent_approval
from security.limiter import Limiter
from security import audit

def test_csrf_all_mutations():
    app = Flask(__name__)
    app.secret_key = 'test-only-not-a-deployment-key'
    install_csrf(app)
    app.add_url_rule('/', view_func=lambda: csrf_token(), methods=['GET', 'POST', 'DELETE'])
    c = app.test_client()
    assert c.post('/').status_code == 400
    token = c.get('/').text
    assert c.post('/', data={'csrf_token': token}).status_code == 200
    assert c.delete('/', headers={'X-CSRF-Token': token}).status_code == 200
    assert c.post('/', data={'csrf_token': 'x' * 64}).status_code == 400
    assert app.test_client().post('/', data={'csrf_token': token}).status_code == 400
    assert c.get('/').headers['Cache-Control'] == 'no-store'

def test_proxy_spoof_rejected():
    assert client_ip('192.0.2.1', '1.2.3.4') == '192.0.2.1'
    assert client_ip('10.0.0.1', 'evil, 192.0.2.1', ['10.0.0.0/8']) == '10.0.0.1'
    assert client_ip('10.0.0.1', '198.51.100.99, 192.0.2.1', ['10.0.0.0/8']) == '192.0.2.1'

def test_scope_and_separation():
    reviewer = Principal('u1', frozenset({'reviewer'}), frozenset({'KA'}))
    approver = Principal('u2', frozenset({'approver'}), frozenset({'KA'}))
    both = Principal('u1', frozenset({'reviewer', 'approver'}), frozenset({'KA'}))
    assert authorized(reviewer, 'verify', 'KA')
    assert not authorized(reviewer, 'approve_decision', 'KA')
    assert not authorized(reviewer, 'verify', 'MH')
    assert not authorized(None, 'verify', 'KA')
    assert independent_approval(reviewer, approver, 'KA')
    assert not independent_approval(reviewer, both, 'KA')

def test_limiter_shared_and_atomic(tmp_path):
    a = Limiter(str(tmp_path / 'limit.db'))
    b = Limiter(a.path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: (a if i % 2 else b).allow('login:peer', 5, 60, now=120), range(20)))
    assert sum(results) == 5
    assert a.allow('login:peer', 5, 60, now=180)
    assert Limiter(str(tmp_path / 'other.db')).allow('x', 1, 60, now=120)
    with pytest.raises(ValueError):
        a.allow('x', 1, 86401, now=120)

def test_chain_changes_truncation_and_rollback():
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    audit.initialize(c)
    first = audit.append(c, 'officer:1', 'verify', 'case:1')
    c.commit()
    second = audit.append(c, 'officer:2', 'approve', 'case:1')
    c.commit()
    rows = [dict(r) for r in c.execute('SELECT * FROM security_audit ORDER BY seq')]
    cp = (2, second['event_hash'])
    assert audit.verify(rows, cp)[0]
    assert not audit.verify(rows[:1], cp)[0]
    rows[0]['action'] = 'tampered'
    assert not audit.verify(rows, cp)[0]
    with pytest.raises(sqlite3.IntegrityError):
        c.execute('DELETE FROM security_audit')
    c.rollback()
    audit.append(c, 'u3', 'dismiss', 'case:2')
    c.rollback()
    assert c.execute('SELECT COUNT(*) FROM security_audit').fetchone()[0] == 2

@pytest.mark.parametrize('value', ['=cmd()', '+1', '-2', '@SUM(1)', '\t=1', '  =1'])
def test_csv_formula_neutralization(value):
    assert csv_cell(value).startswith("'")
