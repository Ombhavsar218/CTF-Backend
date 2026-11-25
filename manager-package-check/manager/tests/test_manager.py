from fastapi.testclient import TestClient

from manager.app.main import app
from manager.app import config, catalog


client = TestClient(app)


def test_health_redacted():
    resp = client.get('/manager/v1/health')
    assert resp.status_code == 200
    data = resp.json()
    assert data == {'status': 'ok', 'version': config.settings.app_version}
    assert 'token' not in str(data).lower()
    assert 'docker' not in str(data).lower()


def test_provision_requires_auth():
    old = config.settings.manager_token
    config.settings.manager_token = 'test'
    try:
        resp = client.post('/manager/v1/provision', json={'request_id': 'r1', 'instance_id': 1, 'challenge_id': 1, 'idempotency_key': 'k1', 'catalog_id': 'nonexistent'})
        assert resp.status_code in (401, 503)
    finally:
        config.settings.manager_token = old


def test_provision_rejects_unknown_fields():
    old = config.settings.manager_token
    config.settings.manager_token = 'test'
    try:
        resp = client.post('/manager/v1/provision', json={'request_id': 'r1', 'instance_id': 1, 'challenge_id': 1, 'idempotency_key': 'k1', 'catalog_id': 'nonexistent', 'image': 'bad'}, headers={'Authorization': 'Bearer test'})
        assert resp.status_code == 422
    finally:
        config.settings.manager_token = old


def test_provision_unavailable_when_auth_configured():
    old = config.settings.manager_token
    config.settings.manager_token = 'test'
    try:
        resp = client.post('/manager/v1/provision', json={'request_id': 'r1', 'instance_id': 1, 'challenge_id': 1, 'idempotency_key': 'k1', 'catalog_id': 'nonexistent'}, headers={'Authorization': 'Bearer test'})
        # Should be rejected by schema (unknown catalog) before reaching handler
        assert resp.status_code == 422
    finally:
        config.settings.manager_token = old


def test_unknown_catalog_id_rejected():
    old = config.settings.manager_token
    config.settings.manager_token = 'test'
    try:
        resp = client.post('/manager/v1/provision', json={'request_id': 'r1', 'instance_id': 1, 'challenge_id': 1, 'idempotency_key': 'k1', 'catalog_id': 'fake'}, headers={'Authorization': 'Bearer test'})
        assert resp.status_code == 422
    finally:
        config.settings.manager_token = old


def test_caller_cannot_override_image():
    old = config.settings.manager_token
    config.settings.manager_token = 'test'
    try:
        resp = client.post('/manager/v1/provision', json={'request_id': 'r1', 'instance_id': 1, 'challenge_id': 1, 'idempotency_key': 'k1', 'catalog_id': 'nonexistent', 'image': 'nginx:latest'}, headers={'Authorization': 'Bearer test'})
        assert resp.status_code == 422
    finally:
        config.settings.manager_token = old


def test_catalog_requires_auth():
    old = config.settings.manager_token
    config.settings.manager_token = 'test'
    try:
        resp = client.get('/manager/v1/catalog')
        assert resp.status_code == 401
    finally:
        config.settings.manager_token = old


def test_catalog_returns_empty_or_valid():
    old = config.settings.manager_token
    config.settings.manager_token = 'test'
    try:
        resp = client.get('/manager/v1/catalog', headers={'Authorization': 'Bearer test'})
        assert resp.status_code == 200
        data = resp.json()
        assert 'entries' in data
        assert data['max_cpu_cores'] <= catalog.MAX_CPU_CORES
        assert data['network_egress_denied_by_default'] is True
    finally:
        config.settings.manager_token = old


def test_runtime_ops_still_unavailable():
    old = config.settings.manager_token
    config.settings.manager_token = 'test'
    try:
        r1 = client.post('/manager/v1/instances/1/inspect', json={'instance_id': 1, 'idempotency_key': 'k'}, headers={'Authorization': 'Bearer test'})
        r2 = client.post('/manager/v1/instances/1/stop', json={'instance_id': 1, 'idempotency_key': 'k'}, headers={'Authorization': 'Bearer test'})
        r3 = client.post('/manager/v1/instances/1/cleanup', json={'instance_id': 1, 'idempotency_key': 'k'}, headers={'Authorization': 'Bearer test'})
        assert r1.status_code == 503
        assert r2.status_code == 503
        assert r3.status_code == 503
    finally:
        config.settings.manager_token = old

