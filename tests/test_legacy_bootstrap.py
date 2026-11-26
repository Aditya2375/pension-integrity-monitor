"""The legacy deployment key (PIM_OFFICER_KEY) becomes the first named admin
account when no named account exists, so an upgraded deployment keeps a way in.
Named accounts (PIM_USERS) always take over: with any user present, the legacy
key bootstrap is a no-op."""
import os
import sys
import tempfile
import pathlib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pim import db, users, workflow as wf


class LegacyKeyBootstrap(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.saved = {k: os.environ.get(k) for k in ("PIM_USERS", "PIM_OFFICER_KEY")}
        self.old_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.dir, "t.sqlite3")
        os.environ.pop("PIM_USERS", None)
        self.c = db.init_db()
        wf.ensure_schema(self.c)

    def tearDown(self):
        self.c.close()
        db.DB_PATH = self.old_path
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_empty_users_legacy_key_creates_admin(self):
        os.environ["PIM_OFFICER_KEY"] = "legacy-key-12345"
        self.assertTrue(users.bootstrap_legacy_key(self.c))
        actor = users.authenticate(self.c, "admin", "legacy-key-12345")
        self.assertIsNotNone(actor)
        self.assertEqual(actor.role, "admin")
        self.assertIsNone(users.authenticate(self.c, "admin", "wrong-key-0000"))

    def test_existing_user_blocks_bootstrap(self):
        os.environ["PIM_USERS"] = "rev1:officer:KA:officer-key-1"
        os.environ["PIM_OFFICER_KEY"] = "legacy-key-12345"
        users.bootstrap_from_env(self.c)
        self.assertFalse(users.bootstrap_legacy_key(self.c))
        self.assertIsNone(users.authenticate(self.c, "admin", "legacy-key-12345"))
        self.assertIsNotNone(users.authenticate(self.c, "rev1", "officer-key-1"))

    def test_no_key_no_bootstrap(self):
        os.environ.pop("PIM_OFFICER_KEY", None)
        self.assertFalse(users.bootstrap_legacy_key(self.c))


if __name__ == "__main__":
    unittest.main()
