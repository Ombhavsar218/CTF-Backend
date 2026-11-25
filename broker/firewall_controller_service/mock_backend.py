from .backend_interface import FirewallBackendInterface
from broker.app.firewall_controller import MockFirewallController
from .mock_helper_executor import MockHelperExecutor
from .helper_authorization import MockHelperAuthorizationProvider
from .helper_contract import FORBIDDEN_AUTH_CLAIM_FIELDS, SCHEMA_VERSION

# Controller->helper boundary sanitization: request JSON cannot establish identity/authorization at helper.
# Transport identity context and caller-supplied auth-claim fields are stripped here (controller already
# enforces its own auth). Direct executor/contract validation remains strict when called without adapter.
_STRIP_BEFORE_HELPER = set(FORBIDDEN_AUTH_CLAIM_FIELDS) | {'peer_uid', 'peer_gid'}


class MockFirewallBackend(FirewallBackendInterface):
    """Narrow adapter: routes controller backend calls through the mock helper executor boundary.

    Identity is obtained per request from an explicitly injected provider. There is no
    implicit UID/GID default: without a provider the helper boundary fails closed. The
    provider is a mock seam only and is NOT kernel-authenticated peer identity.
    """

    def __init__(self, executor=None, identity_provider=None, helper_auth=None):
        self._ctrl = MockFirewallController()
        self._identity_provider = identity_provider
        if executor is not None:
            self._executor = executor
            # keep compatibility view if executor exposes _ctrl
            if hasattr(executor, '_ctrl'):
                self._ctrl = executor._ctrl
        else:
            # No implicit trusted identity: empty allowlists deny everything unless the
            # caller explicitly supplies an authorization policy and an identity provider.
            auth = helper_auth or MockHelperAuthorizationProvider(
                allowed_uids=set(), allowed_gids=set(),
            )
            self._executor = MockHelperExecutor(auth=auth, state_controller=self._ctrl)

    @property
    def executor(self):
        return self._executor

    @property
    def ctrl(self):
        return self._ctrl

    def _identity(self):
        provider = self._identity_provider
        if provider is None:
            return None
        try:
            return provider.get_identity()
        except Exception:
            # Provider unavailable => fail closed.
            return None

    def _prep(self, req):
        r = dict(req or {})
        for k in _STRIP_BEFORE_HELPER:
            r.pop(k, None)
        # The adapter is the component that speaks the helper protocol: it always stamps the
        # exact supported schema version. Caller-supplied values are never trusted.
        r['schema_version'] = SCHEMA_VERSION
        return r

    def _dispatch(self, method, req):
        return self._executor.execute_method(
            method, self._prep(req), identity=self._identity()
        )

    def health_check(self, req):
        return self._dispatch('health_check', req)

    def install_policy(self, req):
        return self._dispatch('install_policy', req)

    def inspect_policy(self, req):
        return self._dispatch('inspect_policy', req)

    def verify_policy(self, req):
        return self._dispatch('verify_policy', req)

    def revoke_policy(self, req):
        return self._dispatch('revoke_policy', req)

    def remove_stale_policy(self, req):
        return self._dispatch('remove_stale_policy', req)

    def reconcile_pending_operations(self, req):
        return self._dispatch('reconcile_pending_operations', req)
