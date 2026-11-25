"""Mocked Stage 1D.3 Docker exec/PTY adapter and service tests."""
import threading
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from challenge_runtime.docker_adapter import DockerAdapter
from challenge_runtime.errors import RuntimeErrorBase
from challenge_runtime.service import ChallengeRuntimeService


class FakeSocket:
    def __init__(self):
        self.closed = False
        self.sent = []

    def sendall(self, data):
        self.sent.append(bytes(data))

    def close(self):
        self.closed = True


class FakeChallenge:
    runtime_access_mode = 'terminal'


class FakeInstance:
    pk = 42
    user_id = 7
    status = 'running'
    is_expired = False
    internal_container_id = 'server-container-id'
    internal_name = ''
    challenge = FakeChallenge()


class FakeUser:
    pk = 7


class ExecAdapterTests(SimpleTestCase):
    def setUp(self):
        self.client = Mock()
        self.adapter = DockerAdapter(client=self.client)

    def test_create_exec_session_uses_tty_stdin_and_no_privileges(self):
        self.client.api.exec_create.return_value = {'Id': 'exec-abc'}
        exec_id = self.adapter.create_exec_session('container-1', ['/bin/sh'])
        self.assertEqual(exec_id, 'exec-abc')
        self.client.api.exec_create.assert_called_once_with(
            'container-1', ['/bin/sh'], stdout=True, stderr=True, stdin=True,
            tty=True, privileged=False, user='',
        )

    def test_start_exec_session_wraps_socket_without_leaking_it(self):
        sock = FakeSocket()
        self.client.api.exec_start.return_value = sock
        session = self.adapter.start_exec_session('exec-abc')
        self.client.api.exec_start.assert_called_once_with(
            'exec-abc', tty=True, socket=True
        )
        self.assertEqual(session.exec_id, 'exec-abc')
        self.assertNotIn('exec-abc', repr(session))

    @patch('challenge_runtime.exec_session._read_from_socket')
    def test_read_write_resize_and_inspect_are_separate_bounded_operations(self, read):
        sock = FakeSocket()
        self.client.api.exec_start.return_value = sock
        session = self.adapter.start_exec_session('exec-abc')

        read.return_value = b'output'
        self.assertEqual(session.read(128), b'output')
        read.assert_called_once_with(sock, 128)

        session.write(b'input')
        self.assertEqual(sock.sent, [b'input'])

        session.resize(40, 100)
        self.client.api.exec_resize.assert_called_once_with(
            'exec-abc', height=40, width=100
        )

        self.client.api.exec_inspect.return_value = {
            'Running': True, 'ExitCode': 0, 'Id': 'exec-abc',
        }
        state = session.inspect()
        self.assertEqual(state, {'running': True, 'exit_code': 0})
        self.assertNotIn('Id', state)

    @patch('challenge_runtime.exec_session._read_from_socket')
    def test_blocking_output_read_does_not_block_input_write(self, read):
        sock = FakeSocket()
        self.client.api.exec_start.return_value = sock
        session = self.adapter.start_exec_session('exec-abc')
        started = threading.Event()
        release = threading.Event()

        def blocking_read(_socket, _amount):
            started.set()
            release.wait(timeout=3)
            return b'output'

        read.side_effect = blocking_read
        reader = threading.Thread(target=session.read, args=(64,), daemon=True)
        reader.start()
        self.assertTrue(started.wait(timeout=2))
        session.write(b'input')
        release.set()
        reader.join(timeout=3)
        self.assertEqual(sock.sent, [b'input'])

    def test_close_is_idempotent_and_never_touches_container(self):
        sock = FakeSocket()
        self.client.api.exec_start.return_value = sock
        session = self.adapter.start_exec_session('exec-abc')
        self.adapter.close_exec_session(session)
        self.adapter.close_exec_session(session)
        self.assertTrue(sock.closed)
        self.client.containers.stop.assert_not_called()
        self.client.containers.remove.assert_not_called()


class OpenTerminalSessionTests(SimpleTestCase):
    def _service(self, info=None):
        adapter = Mock()
        adapter.inspect_container.return_value = info or {
            'id': 'server-container-id',
            'status': 'running',
            'labels': {
                'flaghunt.managed': 'true',
                'flaghunt.instance-id': '42',
                'flaghunt.user-id': '7',
            },
        }
        adapter.create_exec_session.return_value = 'exec-abc'
        adapter.start_exec_session.return_value = Mock()
        return ChallengeRuntimeService(adapter=adapter), adapter

    def test_authorized_instance_uses_server_side_container_and_fixed_shell(self):
        service, adapter = self._service()
        session, exec_id, container_id = service.open_terminal_session(
            FakeInstance(), FakeUser(), ['/bin/sh'], 24, 80
        )
        self.assertEqual(exec_id, 'exec-abc')
        self.assertEqual(container_id, 'server-container-id')
        adapter.create_exec_session.assert_called_once_with(
            'server-container-id', ['/bin/sh'], user='', tty=True
        )
        adapter.start_exec_session.assert_called_once_with('exec-abc', tty=True)
        adapter.resize_exec_session.assert_called_once_with('exec-abc', 24, 80)
        adapter.attach.assert_not_called()
        adapter.stop_container.assert_not_called()
        adapter.remove_container.assert_not_called()
        self.assertIsNotNone(session)

    def test_non_owner_is_rejected_before_any_docker_exec(self):
        service, adapter = self._service()
        other = FakeUser()
        other.pk = 8
        with self.assertRaises(RuntimeErrorBase):
            service.open_terminal_session(FakeInstance(), other, ['/bin/sh'], 24, 80)
        adapter.create_exec_session.assert_not_called()

    def test_stopped_instance_is_rejected(self):
        service, adapter = self._service()
        instance = FakeInstance()
        instance.status = 'stopped'
        with self.assertRaises(RuntimeErrorBase):
            service.open_terminal_session(instance, FakeUser(), ['/bin/sh'], 24, 80)
        adapter.create_exec_session.assert_not_called()

    def test_non_terminal_challenge_is_rejected(self):
        service, adapter = self._service()
        instance = FakeInstance()
        instance.challenge = type('C', (), {'runtime_access_mode': 'http'})()
        with self.assertRaises(RuntimeErrorBase):
            service.open_terminal_session(instance, FakeUser(), ['/bin/sh'], 24, 80)
        adapter.create_exec_session.assert_not_called()

    def test_missing_container_is_rejected(self):
        service, adapter = self._service({'id': 'x', 'status': 'exited', 'labels': {}})
        with self.assertRaises(RuntimeErrorBase):
            service.open_terminal_session(FakeInstance(), FakeUser(), ['/bin/sh'], 24, 80)
        adapter.create_exec_session.assert_not_called()

    def test_reconfirm_failure_closes_started_stream(self):
        service, adapter = self._service()
        stream = Mock()
        adapter.start_exec_session.return_value = stream
        adapter.resize_exec_session.side_effect = RuntimeErrorBase('resize failed')
        with self.assertRaises(RuntimeErrorBase):
            service.open_terminal_session(FakeInstance(), FakeUser(), ['/bin/sh'], 24, 80)
        stream.close.assert_called_once()
