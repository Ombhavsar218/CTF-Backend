"""Test runner that isolates cache-backed throttles between tests.

Throttle counters live in Django's cache, which is process-global and is not
rolled back with the database. Without clearing it, one registration or login
test can consume another test's allowance and the suite becomes order-dependent.
Clearing before every test keeps the production rates untouched while making
the suite deterministic.
"""

import unittest

from django.core.cache import cache
from django.test.runner import DiscoverRunner


class CacheClearingDiscoverRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        """Keep per-request INFO lines out of an already large test suite."""
        super().setup_test_environment(**kwargs)
        from django.conf import settings

        settings.REQUEST_LOG_ENABLED = False

    def get_resultclass(self):
        """Keep Django's normal result class and add cache isolation.

        ``DiscoverRunner`` returns ``None`` for the standard runner and a
        specialised class for ``--debug-sql``/``--pdb``. Wrapping whatever it
        chose preserves those options while clearing throttle state before each
        test's ``setUp`` runs.
        """
        base = super().get_resultclass() or unittest.TextTestResult

        def start_test(result, test):
            cache.clear()
            base.startTest(result, test)

        return type(
            'CacheClearingTestResult',
            (base,),
            {'startTest': start_test},
        )
