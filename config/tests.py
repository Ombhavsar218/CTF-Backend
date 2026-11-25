"""Release-readiness checks for security, observability, and API errors."""

import logging
from types import SimpleNamespace

from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from config.deploy import DEV_SECRET_KEY, deployment_errors
from config.exceptions import GENERIC_SERVER_ERROR
from config.middleware import RequestIDMiddleware
from config.observability import (
    RequestIDFilter,
    bind_request_id,
    get_request_id,
    normalise_request_id,
    redact_sensitive,
    reset_request_id,
    sanitize_log_value,
)


class SecurityHeaderTests(TestCase):
    url = '/api/v1/categories/'

    def test_standard_security_headers_are_present(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(response.headers['Referrer-Policy'], 'same-origin')

    def test_csp_is_report_only_by_default(self):
        response = self.client.get(self.url)

        self.assertIn('Content-Security-Policy-Report-Only', response.headers)
        self.assertNotIn('Content-Security-Policy', response.headers)
        policy = response.headers['Content-Security-Policy-Report-Only']
        self.assertIn("default-src 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)

    @override_settings(CSP_REPORT_ONLY=False)
    def test_csp_can_be_enforced(self):
        response = self.client.get(self.url)

        self.assertIn('Content-Security-Policy', response.headers)
        self.assertNotIn('Content-Security-Policy-Report-Only', response.headers)

    @override_settings(CSP_POLICY='')
    def test_csp_header_is_omitted_when_no_policy_is_configured(self):
        response = self.client.get(self.url)

        self.assertNotIn('Content-Security-Policy', response.headers)
        self.assertNotIn('Content-Security-Policy-Report-Only', response.headers)


class RequestIDTests(TestCase):
    @override_settings(REQUEST_LOG_ENABLED=True)
    def test_a_generated_request_id_is_returned_and_logged(self):
        with self.assertLogs('config.request', level='INFO') as captured:
            response = self.client.get('/api/v1/categories/')

        request_id = response.headers['X-Request-ID']
        self.assertRegex(request_id, r'^[0-9a-f]{32}$')
        logs = '\n'.join(captured.output)
        self.assertIn(f'request_id={request_id}', logs)
        self.assertIn('method=GET', logs)
        self.assertIn('status=200', logs)

    @override_settings(REQUEST_LOG_ENABLED=True)
    def test_a_safe_incoming_request_id_is_echoed(self):
        response = self.client.get(
            '/api/v1/categories/', HTTP_X_REQUEST_ID='web-abc_123:blue'
        )

        self.assertEqual(response.headers['X-Request-ID'], 'web-abc_123:blue')

    def test_an_unsafe_request_id_is_replaced(self):
        factory = RequestFactory()
        request = factory.get(
            '/api/v1/categories/', HTTP_X_REQUEST_ID='bad\r\nX-Injected: yes'
        )
        response = RequestIDMiddleware(lambda req: HttpResponse('ok'))(request)

        self.assertRegex(response.headers['X-Request-ID'], r'^[0-9a-f]{32}$')
        self.assertNotIn('Injected', response.headers['X-Request-ID'])
        self.assertEqual(get_request_id(), '-')

    def test_request_id_length_and_characters_are_bounded(self):
        self.assertEqual(normalise_request_id('abc-123'), 'abc-123')
        self.assertEqual(normalise_request_id('a' * 64), 'a' * 64)
        self.assertIsNone(normalise_request_id('a' * 65))
        self.assertIsNone(normalise_request_id(' leading-space'))
        self.assertIsNone(normalise_request_id('bad\tvalue'))
        self.assertIsNone(normalise_request_id(None))

    @override_settings(REQUEST_LOG_ENABLED=True)
    def test_request_logs_do_not_include_query_strings(self):
        with self.assertLogs('config.request', level='INFO') as captured:
            self.client.get(
                '/api/v1/categories/?password=hunter2&flag=CTF{not_logged}'
            )

        logs = '\n'.join(captured.output)
        self.assertNotIn('hunter2', logs)
        self.assertNotIn('CTF{not_logged}', logs)
        self.assertNotIn('password=', logs)

    @override_settings(REQUEST_LOG_ENABLED=False)
    def test_request_logging_can_be_disabled(self):
        with self.assertNoLogs('config.request', level='INFO'):
            self.client.get('/api/v1/categories/')


@override_settings(ROOT_URLCONF='config.test_urls')
class SafeApiErrorTests(TestCase):
    def test_unhandled_error_returns_safe_json_and_correlation_id(self):
        with self.assertLogs('config.exceptions', level='ERROR') as captured:
            response = self.client.get(
                '/test/unhandled/', HTTP_X_REQUEST_ID='corr-unhandled'
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers['X-Request-ID'], 'corr-unhandled')
        self.assertEqual(response.headers['Content-Type'], 'application/json')
        self.assertEqual(response.json(), {'detail': GENERIC_SERVER_ERROR})

        body = response.content.decode('utf-8')
        self.assertNotIn('RuntimeError', body)
        self.assertNotIn('/srv/secret', body)
        self.assertNotIn('hunter2', body)
        self.assertNotIn('CTF{', body)
        self.assertNotIn('Traceback', body)
        self.assertTrue(captured.output)

    @override_settings(DEBUG=True)
    def test_debug_mode_does_not_leak_a_traceback_through_the_api(self):
        response = self.client.get('/test/unhandled/')

        self.assertEqual(response.status_code, 500)
        self.assertNotIn('Traceback', response.content.decode('utf-8'))
        self.assertEqual(response.json(), {'detail': GENERIC_SERVER_ERROR})

    def test_validation_errors_keep_their_useful_shape(self):
        response = self.client.get('/test/validation/')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {'username': ['This field is required.']}
        )

    def test_permission_errors_keep_their_useful_detail(self):
        response = self.client.get('/test/denied/')

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {'detail': 'You do not have permission to do that.'},
        )

    def test_api_exception_5xx_detail_is_replaced(self):
        response = self.client.get('/test/server-error/')

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {'detail': GENERIC_SERVER_ERROR})
        self.assertNotIn('/srv/secret', response.content.decode('utf-8'))

    def test_deliberate_safe_5xx_detail_is_preserved(self):
        response = self.client.get('/test/service-unavailable/')

        self.assertEqual(response.status_code, 503)
        self.assertIn('setup_groups', response.json()['detail'])
        self.assertNotIn('Traceback', response.content.decode('utf-8'))


class LogHygieneTests(SimpleTestCase):
    def test_common_secret_shapes_are_redacted(self):
        text = (
            'password=hunter2 token=abc123 CTF{do_not_log} '
            'Authorization: Bearer header-value '
            'broker=redis://user:pass@redis:6379/0'
        )
        redacted = redact_sensitive(text)

        for secret in ('hunter2', 'abc123', 'CTF{do_not_log}', 'header-value'):
            self.assertNotIn(secret, redacted)
        self.assertNotIn('user:pass@', redacted)
        self.assertIn('[REDACTED]', redacted)

    def test_log_values_cannot_inject_new_lines(self):
        value = sanitize_log_value('one\r\ntwo\x00three', max_length=100)

        self.assertNotIn('\r', value)
        self.assertNotIn('\n', value)
        self.assertNotIn('\x00', value)
        self.assertEqual(value, 'one??two?three')

    def test_request_filter_prefers_a_safe_request_attribute(self):
        token = bind_request_id('-')
        try:
            record = logging.LogRecord(
                'django.request', logging.ERROR, __file__, 1, 'failed', (), None
            )
            record.request = SimpleNamespace(request_id='django-corr-1')
            RequestIDFilter().filter(record)
            self.assertEqual(record.request_id, 'django-corr-1')

            record.request.request_id = 'bad\r\nInjected'
            RequestIDFilter().filter(record)
            self.assertEqual(record.request_id, '-')
        finally:
            reset_request_id(token)

    def test_logging_formatter_and_handlers_are_configured(self):
        logging_config = settings.LOGGING
        formatter = logging_config['formatters']['standard']['format']

        self.assertIn('%(asctime)s', formatter)
        self.assertIn('%(levelname)s', formatter)
        self.assertIn('%(name)s', formatter)
        self.assertIn('%(module)s', formatter)
        self.assertIn('request_id=%(request_id)s', formatter)
        self.assertIn('console', logging_config['handlers'])
        self.assertEqual(
            logging_config['root']['level'], settings.LOG_LEVEL
        )
        if settings.LOG_FILE is None:
            self.assertNotIn('file', logging_config['handlers'])
        else:
            self.assertIn('file', logging_config['handlers'])
            self.assertEqual(
                logging_config['handlers']['file']['maxBytes'],
                settings.LOG_FILE_MAX_BYTES,
            )

    def test_api_and_cors_observability_settings_are_wired(self):
        self.assertEqual(
            settings.REST_FRAMEWORK['EXCEPTION_HANDLER'],
            'config.exceptions.safe_exception_handler',
        )
        self.assertIn('X-Request-ID', settings.CORS_EXPOSE_HEADERS)


class JwtConfigurationTests(SimpleTestCase):
    def test_refresh_rotation_and_blacklisting_are_enabled_by_default(self):
        self.assertTrue(settings.SIMPLE_JWT['ROTATE_REFRESH_TOKENS'])
        self.assertTrue(settings.SIMPLE_JWT['BLACKLIST_AFTER_ROTATION'])
        self.assertTrue(settings.SIMPLE_JWT['UPDATE_LAST_LOGIN'])

    def test_throttle_rates_are_configured(self):
        rates = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
        for scope in (
            'login',
            'register',
            'token_refresh',
            'flag_submit',
            'hint_reveal',
            'password_change',
        ):
            self.assertIn(scope, rates)

    def test_local_https_enforcement_is_off_by_default(self):
        self.assertFalse(settings.SECURE_SSL_REDIRECT)
        self.assertFalse(settings.SESSION_COOKIE_SECURE)
        self.assertFalse(settings.CSRF_COOKIE_SECURE)
        self.assertEqual(settings.SECURE_HSTS_SECONDS, 0)


class DeploymentValidationTests(SimpleTestCase):
    """Fail-fast rules for production and any DEBUG=False deployment."""

    def config(self, **overrides):
        config = {
            'environment': 'production',
            'debug': False,
            'secret_key': 's' * 64,
            'allowed_hosts': ['ctf.example.com'],
            'cors_allowed_origins': ['https://ctf.example.com'],
            'csrf_trusted_origins': ['https://ctf.example.com'],
            'cache_url': 'redis://127.0.0.1:6379/1',
            'celery_broker_url': 'redis://127.0.0.1:6379/0',
            'secure_ssl_redirect': True,
            'session_cookie_secure': True,
            'csrf_cookie_secure': True,
            'hsts_seconds': 3600,
            'csp_policy': "default-src 'self'; connect-src 'self'",
            'database_engine': 'django.db.backends.sqlite3',
            'database_name': 'db.sqlite3',
        }
        config.update(overrides)
        return config

    def errors_for(self, **overrides):
        return deployment_errors(self.config(**overrides))

    def assert_mentions(self, errors, fragment):
        self.assertTrue(
            any(fragment in error for error in errors),
            f'{fragment!r} not found in {errors!r}',
        )

    def test_a_valid_production_configuration_passes(self):
        self.assertEqual(deployment_errors(self.config()), [])

    def test_development_defaults_remain_zero_config(self):
        self.assertEqual(
            deployment_errors(
                {
                    'environment': 'development',
                    'debug': True,
                    'secret_key': DEV_SECRET_KEY,
                    'allowed_hosts': [],
                    'cors_allowed_origins': ['http://localhost:5173'],
                    'csrf_trusted_origins': [],
                    'cache_url': None,
                    'celery_broker_url': 'redis://127.0.0.1:6379/0',
                    'secure_ssl_redirect': False,
                    'session_cookie_secure': False,
                    'csrf_cookie_secure': False,
                    'hsts_seconds': 0,
                    'csp_policy': (
                        "default-src 'self'; connect-src 'self' "
                        'http://localhost:5173'
                    ),
                    'database_engine': 'django.db.backends.sqlite3',
                    'database_name': 'db.sqlite3',
                }
            ),
            [],
        )

    def test_unknown_environment_is_rejected(self):
        self.assert_mentions(
            self.errors_for(environment='staging'), 'ENVIRONMENT must be'
        )

    def test_production_rejects_debug(self):
        self.assert_mentions(self.errors_for(debug=True), 'DEBUG must be False')

    def test_production_rejects_the_development_secret(self):
        self.assert_mentions(
            self.errors_for(secret_key=DEV_SECRET_KEY),
            'development key or a placeholder',
        )

    def test_production_rejects_a_placeholder_or_short_secret(self):
        self.assert_mentions(
            self.errors_for(secret_key='replace-with-a-secret'),
            'development key or a placeholder',
        )
        self.assert_mentions(
            self.errors_for(secret_key='short'), 'at least 50 characters'
        )

    def test_debug_false_without_a_secret_fails(self):
        self.assert_mentions(
            self.errors_for(
                environment='development', debug=False, secret_key=''
            ),
            'SECRET_KEY must be set explicitly',
        )

    def test_production_rejects_empty_or_wildcard_hosts(self):
        self.assert_mentions(
            self.errors_for(allowed_hosts=[]), 'ALLOWED_HOSTS must contain'
        )
        self.assert_mentions(
            self.errors_for(allowed_hosts=['*']), 'must not contain "*"'
        )
        self.assert_mentions(
            self.errors_for(allowed_hosts=['https://ctf.example.com']),
            'bare hostname',
        )

    def test_production_requires_https_origins(self):
        self.assert_mentions(
            self.errors_for(cors_allowed_origins=['http://ctf.example.com']),
            'must use https',
        )
        self.assert_mentions(
            self.errors_for(
                csrf_trusted_origins=['http://ctf.example.com']
            ),
            'must use https',
        )

    def test_origins_must_be_bare_origins(self):
        self.assert_mentions(
            self.errors_for(
                cors_allowed_origins=['https://ctf.example.com/']
            ),
            'must not include a path',
        )
        self.assert_mentions(
            self.errors_for(
                cors_allowed_origins=['https://*.example.com']
            ),
            'must not contain a wildcard',
        )
        # CSRF_TRUSTED_ORIGINS supports wildcard subdomains.
        self.assertEqual(
            self.errors_for(
                csrf_trusted_origins=['https://*.example.com']
            ),
            [],
        )

    def test_production_requires_a_separate_shared_cache(self):
        self.assert_mentions(
            self.errors_for(cache_url=None), 'CACHE_URL must be set'
        )
        self.assert_mentions(
            self.errors_for(
                cache_url='redis://127.0.0.1:6379/0'
            ),
            'must not be the same Redis URL',
        )
        self.assert_mentions(
            self.errors_for(cache_url='http://127.0.0.1:6379/1'),
            'redis:// or rediss://',
        )

    def test_production_requires_secure_transport_settings(self):
        self.assert_mentions(
            self.errors_for(secure_ssl_redirect=False),
            'SECURE_SSL_REDIRECT must be True',
        )
        self.assert_mentions(
            self.errors_for(session_cookie_secure=False),
            'SESSION_COOKIE_SECURE must be True',
        )
        self.assert_mentions(
            self.errors_for(csrf_cookie_secure=False),
            'CSRF_COOKIE_SECURE must be True',
        )
        self.assert_mentions(
            self.errors_for(hsts_seconds=0),
            'SECURE_HSTS_SECONDS must be greater than 0',
        )

    def test_production_rejects_development_csp_sources(self):
        self.assert_mentions(
            self.errors_for(csp_policy=''),
            'CSP_POLICY must not be empty',
        )
        self.assert_mentions(
            self.errors_for(
                csp_policy="default-src 'self'; connect-src http://localhost:8000"
            ),
            'development origins',
        )
        self.assert_mentions(
            self.errors_for(
                csp_policy="default-src 'self'; connect-src http://api.example.com"
            ),
            'insecure http:// origins',
        )

    def test_non_sqlite_engines_require_a_database_name(self):
        self.assert_mentions(
            self.errors_for(
                database_engine='django.db.backends.postgresql',
                database_name='',
            ),
            'DB_NAME must be set',
        )
