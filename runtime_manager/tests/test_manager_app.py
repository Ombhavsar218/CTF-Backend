import json
from unittest import mock

from django.test import SimpleTestCase

from runtime_manager.auth import authenticate
from runtime_manager.config import ManagerConfig
from runtime_manager.errors import AuthError, ForbiddenError
from runtime_manager.server import RuntimeManagerApp


class FakeOps:
    def __init__(self):
        self.calls = []

    def create(self, payload):
        self.calls.append(("create", payload))
        return {"status": "running", "container_id": "cid1", "created": True, "info": {"id": "cid1", "status": "running", "labels": {"flaghunt.managed": "true", "flaghunt.instance-id": payload["instance_id"], "flaghunt.user-id": payload["user_id"]}}}

    def inspect(self, instance_id, user_id=None):
        self.calls.append(("inspect", instance_id, user_id))
        return {"id": "cid1", "status": "running", "labels": {"flaghunt.managed": "true", "flaghunt.instance-id": str(instance_id), "flaghunt.user-id": str(user_id or "1")}}

    def stop(self, instance_id, user_id=None, timeout=10):
        self.calls.append(("stop", instance_id, user_id))
        return {"status": "exited"}

    def remove(self, instance_id, user_id=None, force=True):
        self.calls.append(("remove", instance_id, user_id, force))
        return {"removed": True}

    def open_terminal(self, instance_id, user_id, shell, rows, cols, expires_at):
        self.calls.append(("open_terminal", instance_id, user_id, shell, rows, cols))
        return {"exec_id": "exec1", "container_id": "cid1"}

    def write_terminal(self, instance_id, exec_id, data_b64, user_id=None):
        return {"written": 1}

    def read_terminal(self, instance_id, exec_id, max_bytes=4096, user_id=None):
        return {"data_b64": "", "eof": False}

    def resize_terminal(self, instance_id, exec_id, rows, cols, user_id=None):
        return {"resized": True}

    def close_terminal(self, instance_id, exec_id, user_id=None):
        return {"closed": True}

    def inspect_terminal(self, instance_id, exec_id, user_id=None):
        return {"running": True, "exit_code": None}


def cfg(**overrides):
    defaults = dict(
        auth_token="secret-token",
        signing_key="",
        allowed_image_digests=("sha256:" + "a" * 64,),
        allowed_image_repos=("example/challenge",),
    )
    defaults.update(overrides)
    return ManagerConfig(**defaults)


class ManagerAuthTests(SimpleTestCase):
    def test_missing_auth_rejected(self):
        app = RuntimeManagerApp(config=cfg(), ops=FakeOps())
        status, data = app.handle("GET", "/v1/health", {}, b"{}")
        self.assertEqual(status, 401)
        self.assertEqual(data["error"], "AUTH_FAILED")

    def test_invalid_auth_rejected(self):
        app = RuntimeManagerApp(config=cfg(), ops=FakeOps())
        status, _ = app.handle("GET", "/v1/health", {"authorization": "Bearer wrong"}, b"{}")
        self.assertEqual(status, 401)

    def test_valid_auth_accepted(self):
        app = RuntimeManagerApp(config=cfg(), ops=FakeOps())
        status, data = app.handle("GET", "/v1/health", {"authorization": "Bearer secret-token"}, b"{}")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")

    def test_unconfigured_manager_fails_closed(self):
        app = RuntimeManagerApp(config=cfg(auth_token=""), ops=FakeOps())
        status, _ = app.handle("GET", "/v1/health", {"authorization": "Bearer anything"}, b"{}")
        self.assertEqual(status, 401)


class ManagerPolicyTests(SimpleTestCase):
    def auth(self):
        return {"authorization": "Bearer secret-token"}

    def test_unknown_fields_rejected(self):
        app = RuntimeManagerApp(config=cfg(), ops=FakeOps())
        body = json.dumps({
            "instance_id": "1", "challenge_id": "2", "user_id": "3",
            "image": "example/challenge", "image_digest": "sha256:" + "a" * 64,
            "runtime_access_mode": "terminal", "runtime_internal_port": None,
            "runtime_command": None, "cpu_limit": 0.25, "memory_mb": 128,
            "pids_limit": 64, "read_only": True, "expires_at": None,
            "evil": "yes",
        }).encode()
        status, data = app.handle("POST", "/v1/instances/create", self.auth(), body)
        self.assertEqual(status, 422)
        self.assertEqual(data["error"], "INVALID_REQUEST")

    def test_unapproved_image_digest_rejected(self):
        app = RuntimeManagerApp(config=cfg(), ops=FakeOps())
        body = json.dumps({
            "instance_id": "1", "challenge_id": "2", "user_id": "3",
            "image": "example/challenge", "image_digest": "sha256:" + "b" * 64,
            "runtime_access_mode": "terminal", "cpu_limit": 0.25, "memory_mb": 128,
            "pids_limit": 64, "read_only": True,
        }).encode()
        status, data = app.handle("POST", "/v1/instances/create", self.auth(), body)
        self.assertEqual(status, 422)

    def test_privileged_limits_rejected(self):
        app = RuntimeManagerApp(config=cfg(), ops=FakeOps())
        body = json.dumps({
            "instance_id": "1", "challenge_id": "2", "user_id": "3",
            "image": "example/challenge", "image_digest": "sha256:" + "a" * 64,
            "runtime_access_mode": "terminal", "cpu_limit": 2.0, "memory_mb": 128,
            "pids_limit": 64, "read_only": True,
        }).encode()
        status, data = app.handle("POST", "/v1/instances/create", self.auth(), body)
        self.assertEqual(status, 422)

    def test_read_only_false_rejected(self):
        app = RuntimeManagerApp(config=cfg(), ops=FakeOps())
        body = json.dumps({
            "instance_id": "1", "challenge_id": "2", "user_id": "3",
            "image": "example/challenge", "image_digest": "sha256:" + "a" * 64,
            "runtime_access_mode": "terminal", "cpu_limit": 0.25, "memory_mb": 128,
            "pids_limit": 64, "read_only": False,
        }).encode()
        status, _ = app.handle("POST", "/v1/instances/create", self.auth(), body)
        self.assertEqual(status, 422)


class ManagerLifecycleTests(SimpleTestCase):
    def auth(self):
        return {"authorization": "Bearer secret-token"}

    def test_create_accepts_valid_terminal_request(self):
        ops = FakeOps()
        app = RuntimeManagerApp(config=cfg(), ops=ops)
        body = json.dumps({
            "instance_id": "1", "challenge_id": "2", "user_id": "3",
            "image": "example/challenge", "image_digest": "sha256:" + "a" * 64,
            "runtime_access_mode": "terminal", "cpu_limit": 0.25, "memory_mb": 128,
            "pids_limit": 64, "read_only": True,
        }).encode()
        status, data = app.handle("POST", "/v1/instances/create", self.auth(), body)
        self.assertEqual(status, 200)
        self.assertEqual(data["instance_id"], "1")
        self.assertEqual(ops.calls[0][0], "create")

    def test_expire_is_idempotent_via_stop_remove(self):
        ops = FakeOps()
        app = RuntimeManagerApp(config=cfg(), ops=ops)
        body = json.dumps({"instance_id": "1", "user_id": "3"}).encode()
        status, _ = app.handle("POST", "/v1/instances/1/expire", self.auth(), body)
        self.assertEqual(status, 200)
        self.assertEqual(ops.calls[0][0], "stop")
        self.assertEqual(ops.calls[1][0], "remove")

    def test_terminal_open_uses_fixed_shell_from_request_validation(self):
        ops = FakeOps()
        app = RuntimeManagerApp(config=cfg(), ops=ops)
        body = json.dumps({
            "instance_id": "1", "user_id": "3", "shell": ["/bin/sh"], "rows": 24, "cols": 80
        }).encode()
        status, data = app.handle("POST", "/v1/instances/1/terminal/open", self.auth(), body)
        self.assertEqual(status, 200)
        self.assertEqual(data["exec_id"], "exec1")

    def test_client_supplied_container_id_field_rejected(self):
        ops = FakeOps()
        app = RuntimeManagerApp(config=cfg(), ops=ops)
        body = json.dumps({"instance_id": "1", "user_id": "3", "container_id": "evil"}).encode()
        status, data = app.handle("POST", "/v1/instances/1/stop", self.auth(), body)
        self.assertEqual(status, 422)
        self.assertEqual(data["error"], "INVALID_REQUEST")

    def test_invalid_shell_rejected(self):
        ops = FakeOps()
        app = RuntimeManagerApp(config=cfg(), ops=ops)
        body = json.dumps({
            "instance_id": "1", "user_id": "3", "shell": "bash -c id", "rows": 24, "cols": 80
        }).encode()
        status, _ = app.handle("POST", "/v1/instances/1/terminal/open", self.auth(), body)
        self.assertEqual(status, 422)

    def test_errors_do_not_leak_auth_token(self):
        ops = FakeOps()
        app = RuntimeManagerApp(config=cfg(auth_token="super-secret-token"), ops=ops)
        status, data = app.handle("GET", "/v1/health", {"authorization": "Bearer wrong"}, b"{}")
        self.assertEqual(status, 401)
        self.assertNotIn("super-secret-token", json.dumps(data))


class ManagerOwnershipTests(SimpleTestCase):
    def auth(self):
        return {"authorization": "Bearer secret-token"}

    def test_forbidden_from_ops_is_403(self):
        ops = FakeOps()
        ops.inspect = mock.Mock(side_effect=ForbiddenError("Ownership verification failed"))
        app = RuntimeManagerApp(config=cfg(), ops=ops)
        body = json.dumps({"instance_id": "1", "user_id": "3"}).encode()
        status, data = app.handle("GET", "/v1/instances/1", self.auth(), body)
        self.assertEqual(status, 403)
        self.assertEqual(data["error"], "FORBIDDEN")
