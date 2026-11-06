from flask.testing import FlaskClient
class FormClient(FlaskClient):
    def post(self, *args, **kwargs):
        with self.session_transaction() as sess:
            sess.setdefault("csrf_token", "test-token-only-not-used-outside-tests")
            token = sess["csrf_token"]
        data = kwargs.setdefault("data", {})
        data.setdefault("csrf_token", token)
        return super().post(*args, **kwargs)
