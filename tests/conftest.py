"""Isolate module-global Flask/SQLite state across test files."""
import os, importlib
import pytest

@pytest.fixture(scope='module', autouse=True)
def isolated_runtime(request, tmp_path_factory):
    name=request.module.__name__
    if not any(x in name for x in ('test_auth','test_flow','test_safeguards','test_security_regressions')):
        yield; return
    from pim import db
    import app
    from tests.http_client import FormClient
    root=tmp_path_factory.mktemp('runtime')
    os.environ['PIM_DB']=str(root/'test.sqlite3')
    os.environ['PIM_CHECKPOINT_DIR']=str(root/'checkpoints')
    os.environ['PIM_OFFICER_KEY']='regression-bootstrap-only' if 'security_regressions' in name else 'officer'
    os.environ['PIM_INSECURE_HTTP']='1'
    importlib.reload(db); importlib.reload(app)
    app.app.test_client_class=FormClient
    app.app.config['TESTING']=True
    # test_auth imports the app object directly; refresh it after reload.
    if 'test_auth' in name: request.module.app=app.app
    yield
