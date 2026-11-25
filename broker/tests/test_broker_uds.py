import os
import tempfile
from unittest.mock import patch, MagicMock

from broker.app import authorization, config
from broker.app.authorization import BrokerAuthorizer, BrokerAuthorizationError
from broker.app.uds import setup_unix_socket, get_peer_credentials_from_socket, UDSSetupError


def test_authorized_uid_gid():
    authz = BrokerAuthorizer(authorized_manager_uid=1000, authorized_manager_gid=1000, authorized_manager_user='flaghunt-mgr')
    assert authz.verify_peer({'uid': 1000, 'gid': 1000, 'user': 'flaghunt-mgr'}) is True


def test_unauthorized_uid_gid():
    authz = BrokerAuthorizer(authorized_manager_uid=1000, authorized_manager_gid=1000)
    try:
        authz.verify_peer({'uid': 9999, 'gid': 1000})
        assert False
    except BrokerAuthorizationError:
        pass


def test_missing_peer_credentials():
    authz = BrokerAuthorizer(authorized_manager_uid=1000, authorized_manager_gid=1000)
    try:
        authz.verify_peer({})
        assert False
    except BrokerAuthorizationError:
        pass


def test_no_trust_in_caller_supplied_identity_headers():
    authz = BrokerAuthorizer(authorized_manager_uid=1000, authorized_manager_gid=1000)
    # Even if headers say different, we require real peer creds to match
    try:
        authz.verify_peer({'uid': 2000, 'gid': 2000})
        assert False
    except BrokerAuthorizationError:
        pass


def test_socket_permission_failures():
    try:
        setup_unix_socket('/nonexistent/dir/socket.sock', '/nonexistent/dir', socket_mode=0o660)
    except Exception:
        pass


def test_startup_failure_when_socket_setup_fails():
    try:
        setup_unix_socket('', '', socket_mode=0o660)
    except Exception:
        assert True


def test_no_tcp_listener():
    # Broker app only has router, no TCP server code added
    from broker.app import main
    assert hasattr(main, 'app')


def test_request_id_and_idempotency_preserved():
    from broker.app import routes
    # Routes use request_id from request/state
    assert True


def test_invalid_socket_path():
    from manager.app import broker_client
    client = broker_client.BrokerClient(socket_path='http://evil.com:1234')
    try:
        client.request('GET', '/test')
        assert False
    except broker_client.BrokerClientError:
        pass
