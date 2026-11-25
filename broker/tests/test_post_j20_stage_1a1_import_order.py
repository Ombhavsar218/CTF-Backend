"""Import-order/process-boundary regression tests for Stage 1A.1 (mock-only).

Exercises relevant import orders in fresh Python processes to prevent
import-order-sensitive circular dependency regressions.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_import_app_firewall_controller_first():
    # Previously failed during collection/import with circular import.
    r = _run(
        """
        from broker.app.firewall_controller import MockFirewallController
        c = MockFirewallController()
        assert c.controller_id == 'mock-controller'
        print('ok')
        """
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "ok" in r.stdout


def test_import_contract_test_module_isolated_collection():
    # Mirrors the previously failing isolated collection context.
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "broker/tests/test_firewall_controller_contract.py", "-q"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"


def test_import_service_before_app_controller():
    r = _run(
        """
        from broker.firewall_controller_service import FirewallControllerService
        from broker.app.firewall_controller import MockFirewallController
        assert FirewallControllerService is not None
        assert MockFirewallController().controller_id == 'mock-controller'
        print('ok')
        """
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "ok" in r.stdout


def test_import_mock_backend_and_app_controller_orders():
    r = _run(
        """
        from broker.firewall_controller_service.mock_backend import MockFirewallBackend
        from broker.app.firewall_controller import MockFirewallController
        assert MockFirewallBackend is not None
        assert MockFirewallController is not None
        print('ok')
        """
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "ok" in r.stdout


def test_import_app_controller_then_service_and_mock_backend():
    r = _run(
        """
        from broker.app.firewall_controller import MockFirewallController
        from broker.firewall_controller_service.mock_backend import MockFirewallBackend
        from broker.firewall_controller_service import FirewallControllerService
        assert MockFirewallController().controller_id == 'mock-controller'
        assert MockFirewallBackend is not None
        assert FirewallControllerService is not None
        print('ok')
        """
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "ok" in r.stdout
