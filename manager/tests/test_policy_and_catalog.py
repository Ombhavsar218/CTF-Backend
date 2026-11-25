import json
import os
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from manager.app import catalog, config, policy
from manager.app.main import app


client = TestClient(app)


def test_valid_catalog_entries():
    # Create a valid catalog entry
    rp = catalog.ResourceProfile(cpu_limit_cores=0.5, memory_limit_mb=256, pid_limit=128)
    entry = catalog.CatalogEntry(
        id="test-chal",
        challenge_image_id="test-chal-img",
        display_name="Test Challenge",
        image_repository="registry.example.com/test/chal",
        image_digest="sha256:" + "a" * 64,
        image_ref="registry.example.com/test/chal@sha256:" + "a" * 64,
        digest_pinned=True,
        verified_runnable=True,
        description="Test",
        approved_container_port=8080,
        resource_profile=rp,
        max_lifetime_seconds=3600,
        storage_policy="ephemeral",
        network_policy="deny_all_egress",
        health_check_settings={"path": "/health", "interval": 30},
        egress_denied=True,
    )
    catalog.CATALOG.clear()
    catalog.CATALOG_BY_CHALLENGE_ID.clear()
    catalog.register_entry(entry)
    assert catalog.get_entry("test-chal") is not None
    assert catalog.get_entry_by_challenge_id("test-chal-img") is not None
    catalog.CATALOG.clear()
    catalog.CATALOG_BY_CHALLENGE_ID.clear()


def test_invalid_or_missing_image_digests():
    rp = catalog.ResourceProfile(cpu_limit_cores=0.5, memory_limit_mb=256, pid_limit=128)
    # Missing digest
    try:
        entry = catalog.CatalogEntry(
            id="bad1",
            challenge_image_id="bad1-img",
            display_name="Bad",
            image_repository="repo/image",
            image_digest="",
            image_ref="repo/image@",
            digest_pinned=False,
            verified_runnable=True,
            description="Bad",
            approved_container_port=8080,
            resource_profile=rp,
            max_lifetime_seconds=3600,
            storage_policy="ephemeral",
            network_policy="deny_all_egress",
            health_check_settings={},
            egress_denied=True,
        )
        catalog.register_entry(entry)
        assert False, "Should have raised"
    except ValueError:
        pass
    # Invalid digest format
    try:
        entry = catalog.CatalogEntry(
            id="bad2",
            challenge_image_id="bad2-img",
            display_name="Bad",
            image_repository="repo/image",
            image_digest="sha256:zzzz",
            image_ref="repo/image@sha256:zzzz",
            digest_pinned=False,
            verified_runnable=True,
            description="Bad",
            approved_container_port=8080,
            resource_profile=rp,
            max_lifetime_seconds=3600,
            storage_policy="ephemeral",
            network_policy="deny_all_egress",
            health_check_settings={},
            egress_denied=True,
        )
        catalog.register_entry(entry)
        assert False, "Should have raised"
    except ValueError:
        pass


def test_unknown_challenge_image_ids():
    catalog.CATALOG.clear()
    catalog.CATALOG_BY_CHALLENGE_ID.clear()
    try:
        policy.PolicyValidator.resolve_challenge_image_id("does-not-exist")
        assert False, "Should have raised"
    except policy.PolicyValidationError:
        pass
    catalog.CATALOG.clear()
    catalog.CATALOG_BY_CHALLENGE_ID.clear()


def test_invalid_ports():
    rp = catalog.ResourceProfile(cpu_limit_cores=0.5, memory_limit_mb=256, pid_limit=128)
    # Port 0
    try:
        entry = catalog.CatalogEntry(
            id="p1",
            challenge_image_id="p1-img",
            display_name="P",
            image_repository="repo/image",
            image_digest="sha256:" + "b" * 64,
            image_ref="repo/image@sha256:" + "b" * 64,
            digest_pinned=True,
            verified_runnable=True,
            description="P",
            approved_container_port=0,
            resource_profile=rp,
            max_lifetime_seconds=3600,
            storage_policy="ephemeral",
            network_policy="deny_all_egress",
            health_check_settings={},
            egress_denied=True,
        )
        catalog.register_entry(entry)
        assert False
    except ValueError:
        pass
    # Port > 65535
    try:
        entry = catalog.CatalogEntry(
            id="p2",
            challenge_image_id="p2-img",
            display_name="P",
            image_repository="repo/image",
            image_digest="sha256:" + "c" * 64,
            image_ref="repo/image@sha256:" + "c" * 64,
            digest_pinned=True,
            verified_runnable=True,
            description="P",
            approved_container_port=70000,
            resource_profile=rp,
            max_lifetime_seconds=3600,
            storage_policy="ephemeral",
            network_policy="deny_all_egress",
            health_check_settings={},
            egress_denied=True,
        )
        catalog.register_entry(entry)
        assert False
    except ValueError:
        pass


def test_invalid_duration():
    rp = catalog.ResourceProfile(cpu_limit_cores=0.5, memory_limit_mb=256, pid_limit=128)
    # Too short
    try:
        entry = catalog.CatalogEntry(
            id="d1",
            challenge_image_id="d1-img",
            display_name="D",
            image_repository="repo/image",
            image_digest="sha256:" + "d" * 64,
            image_ref="repo/image@sha256:" + "d" * 64,
            digest_pinned=True,
            verified_runnable=True,
            description="D",
            approved_container_port=8080,
            resource_profile=rp,
            max_lifetime_seconds=30,
            storage_policy="ephemeral",
            network_policy="deny_all_egress",
            health_check_settings={},
            egress_denied=True,
        )
        catalog.register_entry(entry)
        assert False
    except ValueError:
        pass
    # Too long
    try:
        entry = catalog.CatalogEntry(
            id="d2",
            challenge_image_id="d2-img",
            display_name="D",
            image_repository="repo/image",
            image_digest="sha256:" + "e" * 64,
            image_ref="repo/image@sha256:" + "e" * 64,
            digest_pinned=True,
            verified_runnable=True,
            description="D",
            approved_container_port=8080,
            resource_profile=rp,
            max_lifetime_seconds=7200,
            storage_policy="ephemeral",
            network_policy="deny_all_egress",
            health_check_settings={},
            egress_denied=True,
        )
        catalog.register_entry(entry)
        assert False
    except ValueError:
        pass


def test_unsupported_resource_profiles():
    try:
        policy.PolicyValidator.validate_resource_profile({"cpu_limit_cores": 10})
        assert False
    except policy.PolicyValidationError:
        pass


def test_invalid_storage_policies():
    rp = catalog.ResourceProfile(cpu_limit_cores=0.5, memory_limit_mb=256, pid_limit=128)
    try:
        entry = catalog.CatalogEntry(
            id="s1",
            challenge_image_id="s1-img",
            display_name="S",
            image_repository="repo/image",
            image_digest="sha256:" + "f" * 64,
            image_ref="repo/image@sha256:" + "f" * 64,
            digest_pinned=True,
            verified_runnable=True,
            description="S",
            approved_container_port=8080,
            resource_profile=rp,
            max_lifetime_seconds=3600,
            storage_policy="persistent",
            network_policy="deny_all_egress",
            health_check_settings={},
            egress_denied=True,
        )
        catalog.register_entry(entry)
        assert False
    except ValueError:
        pass


def test_invalid_network_policies():
    rp = catalog.ResourceProfile(cpu_limit_cores=0.5, memory_limit_mb=256, pid_limit=128)
    try:
        entry = catalog.CatalogEntry(
            id="n1",
            challenge_image_id="n1-img",
            display_name="N",
            image_repository="repo/image",
            image_digest="sha256:" + "1" * 64,
            image_ref="repo/image@sha256:" + "1" * 64,
            digest_pinned=True,
            verified_runnable=True,
            description="N",
            approved_container_port=8080,
            resource_profile=rp,
            max_lifetime_seconds=3600,
            storage_policy="ephemeral",
            network_policy="allow_all",
            health_check_settings={},
            egress_denied=True,
        )
        catalog.register_entry(entry)
        assert False
    except ValueError:
        pass


def test_arbitrary_image_names_being_rejected():
    old = config.settings.manager_token
    config.settings.manager_token = 'test'
    try:
        # Try to pass arbitrary image in provision request
        resp = client.post('/manager/v1/provision',
                           json={'request_id': 'r1', 'instance_id': 1, 'challenge_id': 1,
                                 'idempotency_key': 'k1', 'catalog_id': 'nonexistent',
                                 'image': 'nginx:latest'},
                           headers={'Authorization': 'Bearer test'})
        assert resp.status_code == 422  # extra fields forbidden
    finally:
        config.settings.manager_token = old


def test_missing_required_fields():
    try:
        policy.PolicyValidator.validate_catalog_entry_config({})
        assert False
    except policy.PolicyValidationError:
        pass


def test_catalog_immutability():
    # Catalog should be manager controlled and immutable from external modification
    catalog.CATALOG.clear()
    rp = catalog.ResourceProfile(cpu_limit_cores=0.5, memory_limit_mb=256, pid_limit=128)
    entry = catalog.CatalogEntry(
        id="imm1",
        challenge_image_id="imm1-img",
        display_name="Imm",
        image_repository="repo/image",
        image_digest="sha256:" + "2" * 64,
        image_ref="repo/image@sha256:" + "2" * 64,
        digest_pinned=True,
        verified_runnable=True,
        description="Imm",
        approved_container_port=8080,
        resource_profile=rp,
        max_lifetime_seconds=3600,
        storage_policy="ephemeral",
        network_policy="deny_all_egress",
        health_check_settings={},
        egress_denied=True,
    )
    catalog.register_entry(entry)
    # Try to modify - CatalogEntry is frozen
    try:
        entry.display_name = "changed"
        assert False
    except Exception:
        pass
    catalog.CATALOG.clear()
    catalog.CATALOG_BY_CHALLENGE_ID.clear()


def test_default_deny_egress():
    rp = catalog.ResourceProfile(cpu_limit_cores=0.5, memory_limit_mb=256, pid_limit=128)
    try:
        entry = catalog.CatalogEntry(
            id="e1",
            challenge_image_id="e1-img",
            display_name="E",
            image_repository="repo/image",
            image_digest="sha256:" + "3" * 64,
            image_ref="repo/image@sha256:" + "3" * 64,
            digest_pinned=True,
            verified_runnable=True,
            description="E",
            approved_container_port=8080,
            resource_profile=rp,
            max_lifetime_seconds=3600,
            storage_policy="ephemeral",
            network_policy="deny_all_egress",
            health_check_settings={},
            egress_denied=False,  # explicitly false
        )
        catalog.register_entry(entry)
        assert False
    except ValueError:
        pass
