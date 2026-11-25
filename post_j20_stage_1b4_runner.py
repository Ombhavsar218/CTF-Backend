"""Stage 1B.4 evidence runner: captures stdout/stderr/elapsed/summary/exit."""
from __future__ import annotations

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(ROOT, 'venv', 'Scripts', 'python.exe')

SUITES = [
    ('new_1b4', ['broker/tests/test_post_j20_stage_1b4_cross_table_concurrency.py']),
    ('stage_1b1', ['broker/tests/test_post_j20_stage_1b1_durable_lifecycle_intent.py']),
    ('stage_1b2', ['broker/tests/test_post_j20_stage_1b2_atomic_persistence_boundaries.py']),
    ('stage_1b3', ['broker/tests/test_post_j20_stage_1b3_durable_crash_recovery.py']),
    ('j8', ['broker/tests/test_firewall_controller_j8_hardening.py']),
    ('j9', ['broker/tests/test_firewall_controller_j9_reconciliation_integrity.py']),
    ('j10', ['broker/tests/test_firewall_controller_j10_reconciliation_hardening.py']),
    ('j12', ['broker/tests/test_firewall_controller_j12_fault_injection_and_races.py']),
    ('j13', ['broker/tests/test_firewall_controller_j13_transaction_boundary_and_recovery.py']),
    ('j17', ['broker/tests/test_firewall_controller_j17_persistence_integrity.py']),
    ('full', ['broker/tests']),
]


def run(name, targets):
    cmd = [PY, '-m', 'pytest', *targets, '-q']
    started = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elapsed = time.time() - started
    out = proc.stdout.decode('utf-8', errors='replace')
    err = proc.stderr.decode('utf-8', errors='replace')
    with open(os.path.join(ROOT, f'post_j20_stage_1b4_{name}.stdout.txt'), 'w', encoding='utf-8') as f:
        f.write(out)
    with open(os.path.join(ROOT, f'post_j20_stage_1b4_{name}.stderr.txt'), 'w', encoding='utf-8') as f:
        f.write(err)
    summary = next((line.strip() for line in reversed(out.splitlines())
                    if 'passed' in line or 'failed' in line or 'error' in line.lower()), '<none>')
    with open(os.path.join(ROOT, f'post_j20_stage_1b4_{name}.exit.txt'), 'w', encoding='utf-8') as f:
        f.write(f'EXIT={proc.returncode}\nELAPSED_SECONDS={elapsed:.2f}\nSUMMARY={summary}\n')
    print(f'[{name}] {summary} | exit={proc.returncode} | {elapsed:.2f}s', flush=True)
    return proc.returncode


if __name__ == '__main__':
    failures = []
    only = sys.argv[1:] or [s[0] for s in SUITES]
    for name, targets in SUITES:
        if name not in only:
            continue
        if run(name, targets) != 0:
            failures.append(name)
    print('FAILURES:', failures)
    sys.exit(1 if failures else 0)
