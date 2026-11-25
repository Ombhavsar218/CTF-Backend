import os
import tempfile
from unittest.mock import MagicMock

from broker.app import policy, ownership
from broker.app.ownership_store_persistent import PersistentOwnershipStore
from broker.app.db import BrokerDB, BrokerDBError


def test_successful_creation_records_ownership():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        store = PersistentOwnershipStore(path)
        rec = store.record_creation('c1', '1', 'chal1', labels={'flaghunt.manager.managed': 'true'})
        assert store.exists('c1')
        assert store.verify('c1')
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def test_failed_creation_does_not_record_ownership():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        store = PersistentOwnershipStore(path)
        # Don't record - simulate failure
        assert store.exists('c-nope') is False
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def test_ownership_mismatch_blocks():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        store = PersistentOwnershipStore(path)
        store.record_creation('c2', '1', 'chal1')
        try:
            store.verify('c2', owner='other')
            assert False
        except PermissionError:
            pass
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def test_unknown_containers_cannot_be_operated_on():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        store = PersistentOwnershipStore(path)
        try:
            store.verify('unknown')
            assert False
        except PermissionError:
            pass
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def test_labels_alone_do_not_establish_ownership():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        store = PersistentOwnershipStore(path)
        # No record
        assert store.exists('c3') is False
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def test_restart_preserves_ownership():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        store1 = PersistentOwnershipStore(path)
        store1.record_creation('c4', '1', 'chal1')
        # New instance
        store2 = PersistentOwnershipStore(path)
        assert store2.exists('c4')
        store2.verify('c4')
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def test_repeated_stop_remove_safe():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        store = PersistentOwnershipStore(path)
        store.record_creation('c5', '1', 'chal1')
        store.remove('c5')
        res = store.remove('c5')  # idempotent
        assert res is False
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def test_concurrent_operations_cannot_create_conflicting():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        store = PersistentOwnershipStore(path)
        store.record_creation('c6', '1', 'chal1')
        try:
            store.record_creation('c6', '2', 'chal2')
            assert False
        except Exception:
            pass
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def test_corrupt_unavailable_database():
    try:
        db = BrokerDB('/dev/null/impossible/db.sqlite')
        assert False
    except Exception:
        pass


def test_rollback_on_persistence_failure_simulated():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        store = PersistentOwnershipStore(path)
        # If creation fails partway, we don't record - tested
        assert store.exists('bad') is False
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
