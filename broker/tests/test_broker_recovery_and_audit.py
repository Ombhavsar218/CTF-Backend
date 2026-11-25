import os
import stat
import tempfile

import pytest

from broker.app.recovery import OrphanRegistry
from broker.app.db import BrokerDB, BrokerDBError
from broker.app.ownership_store_persistent import PersistentOwnershipStore
from broker.app.audit_persistent import PersistentAuditLogger


def _tmp_db():
    root = tempfile.mkdtemp(prefix='flaghunt-db-')
    return os.path.join(root, 'store', 'broker.db')


def _cleanup(path):
    for suffix in ('', '-wal', '-shm'):
        try:
            os.unlink(path + suffix)
        except Exception:
            pass
    try:
        parent = os.path.dirname(path)
        os.rmdir(parent)
        os.rmdir(os.path.dirname(parent))
    except Exception:
        pass


def _impossible_path():
    """Return a path whose parent is an existing *file*, so it can never be created."""
    fd, f = tempfile.mkstemp(prefix='flaghunt-notadir-')
    os.close(fd)
    return os.path.join(f, 'nested', 'broker.db')


# ---------------------------------------------------------------- orphan storage

def test_orphan_record_survives_restart():
    path = _tmp_db()
    try:
        reg1 = OrphanRegistry(db_path=path)
        reg1.mark_orphan('c1', '1', 'chal', reason='persistence_failed', request_id='r1')
        assert reg1.is_orphan('c1')

        # Simulate broker restart with a fresh registry object.
        reg2 = OrphanRegistry(db_path=path)
        assert reg2.is_orphan('c1')
        rec = reg2.get('c1')
        assert rec.reason == 'persistence_failed'
        assert rec.request_id == 'r1'
        assert rec.cleanup_status == 'unconfirmed'
    finally:
        _cleanup(path)


def test_orphan_duplicate_prevented():
    path = _tmp_db()
    try:
        reg = OrphanRegistry(db_path=path)
        reg.mark_orphan('dup', '1', 'chal', reason='x', request_id='r1')
        reg.mark_orphan('dup', '1', 'chal', reason='y', request_id='r2')
        rows = reg.db.query('SELECT * FROM orphan_recovery WHERE container_id = ?', ('dup',))
        assert len(rows) == 1
        assert rows[0]['reason'] == 'x'
    finally:
        _cleanup(path)


def test_pending_lists_unresolved_only():
    path = _tmp_db()
    try:
        reg = OrphanRegistry(db_path=path)
        reg.mark_orphan('a', '1', 'chal', reason='x')
        reg.mark_orphan('b', '2', 'chal', reason='y')
        reg.confirm_cleanup('a')
        pending = {r.container_id for r in reg.pending()}
        assert 'a' not in pending
        assert 'b' in pending
    finally:
        _cleanup(path)


def test_reconcile_confirms_only_after_success():
    path = _tmp_db()
    try:
        reg = OrphanRegistry(db_path=path)
        reg.mark_orphan('orph', '1', 'chal', reason='x')
        calls = []

        def failing_remover(cid):
            calls.append(cid)
            raise RuntimeError('still running')

        assert reg.reconcile('orph', failing_remover) is False
        assert calls == ['orph']
        # Not confirmed after failure.
        assert reg.get('orph').cleanup_status != 'confirmed'

        def good_remover(cid):
            calls.append(cid)

        assert reg.reconcile('orph', good_remover) is True
        assert reg.get('orph').cleanup_status == 'confirmed'
    finally:
        _cleanup(path)


def test_reconcile_rejects_untrusted_external_id():
    path = _tmp_db()
    try:
        reg = OrphanRegistry(db_path=path)
        called = []

        def remover(cid):
            called.append(cid)

        with pytest.raises(PermissionError):
            reg.reconcile('never-registered', remover)
        assert called == []  # remover never invoked for untrusted id
    finally:
        _cleanup(path)


def test_orphan_record_never_silently_discarded():
    path = _tmp_db()
    try:
        reg = OrphanRegistry(db_path=path)
        reg.mark_orphan('keep', '1', 'chal', reason='x')
        # A new registry must not drop the unresolved record.
        reg2 = OrphanRegistry(db_path=path)
        assert reg2.is_orphan('keep')
        assert reg2.get('keep').cleanup_status == 'unconfirmed'
    finally:
        _cleanup(path)


def test_orphan_registry_fails_closed_without_persistence():
    with pytest.raises(BrokerDBError):
        OrphanRegistry(db_path=_impossible_path())


def test_orphan_persistence_write_failure_is_surfaced():
    path = _tmp_db()
    try:
        reg = OrphanRegistry(db_path=path)

        class Boom:
            def _get_conn(self):
                raise BrokerDBError('disk full')

        reg.db = Boom()
        with pytest.raises(BrokerDBError):
            reg.mark_orphan('lost', '1', 'chal', reason='x')
        # The record is still tracked in-process so it is not silently dropped.
        assert reg.is_orphan('lost')
    finally:
        _cleanup(path)


# ---------------------------------------------------------- database permissions

def test_db_directory_and_file_permissions():
    path = _tmp_db()
    try:
        BrokerDB(path)
        d = os.path.dirname(os.path.abspath(path))
        assert os.path.isdir(d)
        if os.name == 'posix':
            dir_mode = stat.S_IMODE(os.stat(d).st_mode)
            assert dir_mode & 0o007 == 0  # no world access
            file_mode = stat.S_IMODE(os.stat(path).st_mode)
            assert file_mode & 0o007 == 0  # no world access
    finally:
        _cleanup(path)


def test_sidecar_files_are_hardened_when_present():
    path = _tmp_db()
    try:
        db = BrokerDB(path)
        db.execute('INSERT OR IGNORE INTO schema_version (version) VALUES (1)')
        if os.name == 'posix':
            for suffix in ('', '-wal', '-shm'):
                p = path + suffix
                if os.path.exists(p):
                    assert stat.S_IMODE(os.stat(p).st_mode) & 0o007 == 0
    finally:
        _cleanup(path)


def test_db_initialization_failure_fails_closed():
    # A path that cannot be a database must raise, not silently degrade.
    with pytest.raises(BrokerDBError):
        BrokerDB(_impossible_path())


def test_locked_database_fails_closed(monkeypatch):
    """A locked/blocked database must not silently succeed."""
    import sqlite3
    path = _tmp_db()
    try:
        db = BrokerDB(path)

        def boom(*a, **k):
            raise sqlite3.OperationalError('database is locked')

        monkeypatch.setattr(db, '_get_conn', boom)
        with pytest.raises(BrokerDBError):
            db.execute('INSERT INTO schema_version (version) VALUES (99)')
    finally:
        _cleanup(path)


def test_corrupt_database_fails_closed():
    path = _tmp_db()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(b'this is definitely not a sqlite database' * 100)
        with pytest.raises(BrokerDBError):
            BrokerDB(path)
    finally:
        _cleanup(path)


# ------------------------------------------------------------- audit fail-closed

def test_audit_storage_unavailable_fails_closed_on_init():
    with pytest.raises(BrokerDBError):
        PersistentAuditLogger(_impossible_path())


def test_audit_write_failure_does_not_crash_caller():
    path = _tmp_db()
    try:
        audit = PersistentAuditLogger(path)

        class Boom:
            def execute(self, *a, **k):
                raise BrokerDBError('disk full')

        audit.db = Boom()
        # Must not raise: audit failure is reported out-of-band, not by crashing.
        audit.log('op', {'token': 'secret'}, request_id='r1', result='ok')
    finally:
        _cleanup(path)


def test_audit_redacts_secrets():
    path = _tmp_db()
    try:
        audit = PersistentAuditLogger(path)
        audit.log('op', {'token': 'supersecret', 'password': 'p'}, request_id='r1')
        rows = audit.db.query('SELECT * FROM audit_log')
        assert len(rows) >= 1
        # No raw secret should be present anywhere in the stored row.
        assert 'supersecret' not in str(dict(rows[0]))
    finally:
        _cleanup(path)


def test_ownership_write_failure_raises():
    path = _tmp_db()
    try:
        store = PersistentOwnershipStore(path)
        class Boom:
            def _get_conn(self):
                raise BrokerDBError('disk full')
        store.db = Boom()
        with pytest.raises(Exception):
            store.record_creation('c1', '1', 'chal')
    finally:
        _cleanup(path)


def test_restart_after_incomplete_recovery_preserves_state():
    path = _tmp_db()
    try:
        reg1 = OrphanRegistry(db_path=path)
        reg1.mark_orphan('inc', '1', 'chal', reason='persistence_failed_cleanup_unconfirmed', request_id='r9')
        # Broker crashes/restarts before reconciliation.
        reg2 = OrphanRegistry(db_path=path)
        pending = {r.container_id for r in reg2.pending()}
        assert 'inc' in pending
        assert reg2.get('inc').cleanup_status == 'unconfirmed'
    finally:
        _cleanup(path)
