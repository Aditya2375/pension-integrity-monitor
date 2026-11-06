import os, tempfile, pathlib, sys, sqlite3, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ['PIM_DB'] = tempfile.mktemp(suffix='.sqlite3')
os.environ['PIM_CHECKPOINT_DIR'] = tempfile.mkdtemp()
os.environ['PIM_OFFICER_KEY'] = 'regression-bootstrap-only'
os.environ['PIM_INSECURE_HTTP'] = '1'
import app as mod
from pim import db, pipeline
from tests.http_client import FormClient

class SecurityTests(unittest.TestCase):
    def setUp(self):
        mod.app.config['TESTING'] = True
        mod._ATTEMPTS.clear()
    def test_csrf_fail_closed(self):
        from flask.testing import FlaskClient
        raw = FlaskClient(mod.app)
        self.assertEqual(raw.post('/login', data={'username':'admin','key':'regression-bootstrap-only'}).status_code, 400)
        raw.get('/login')
        self.assertEqual(raw.post('/login', data={'csrf_token':'wrong'}).status_code, 400)
    def test_reviewers_cannot_create_accounts(self):
        c = db.connect()
        if not c.execute("SELECT 1 FROM officers WHERE username='review-only'").fetchone():
            db.create_officer(c, 'review-only', 'review-password-only')
        c.execute("UPDATE officers SET must_change=0 WHERE username='review-only'")
        c.commit(); c.close()
        client = FormClient(mod.app)
        client.post('/login', data={'username':'review-only','key':'review-password-only'})
        self.assertEqual(client.post('/officers/add', data={'username':'fake','password':'not-a-real-secret','admin_password':'review-password-only'}).status_code,403)
    def test_inconsistent_audit_cannot_be_extended(self):
        c=db.connect()
        db.log(c,'tester','baseline','');c.commit()
        anchor=db._anchor_path()
        original=pathlib.Path(anchor).read_text()
        pathlib.Path(anchor).write_text('malformed\n')
        try:
            self.assertIs(db.verify_audit(c)[0],False)
            with self.assertRaises(sqlite3.IntegrityError):db.log(c,'tester','should-fail','')
            c.rollback()
        finally:
            pathlib.Path(anchor).write_text(original)
            c.close()
    def test_default_anchor_tracks_database_path(self):
        self.assertEqual(db._anchor_path(),db.DB_PATH+'.anchor')
    def test_tracking_entropy(self):
        tokens = {mod._tracking_id() for _ in range(100)}
        self.assertEqual(len(tokens),100)
        self.assertTrue(all(len(t)==44 for t in tokens))
    def test_schema_migration_is_idempotent(self):
        c = db.connect()
        c.execute('CREATE TABLE IF NOT EXISTS test_marker(x)'); c.commit(); c.close()
        db.init_db().close(); db.init_db().close()
        c=db.connect()
        columns={r['name'] for r in c.execute('PRAGMA table_info(officers)')}
        self.assertTrue({'role','session_version','must_change'} <= columns)
        c.close()
    def test_pipeline_cap_not_shadowed_by_weak_evidence(self):
        import inspect
        source=inspect.getsource(pipeline.run_pipeline)
        self.assertIn('made >= case_cap',source)
        self.assertIn('made + sampled >= case_cap',source)
        self.assertIn("'VERIFICATION','HELD','HOLD_PENDING'",source)

if __name__=='__main__': unittest.main()
