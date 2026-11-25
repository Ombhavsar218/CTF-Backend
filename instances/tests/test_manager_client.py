from unittest.mock import Mock, patch

import requests
from django.test import TestCase, override_settings

from instances import manager_client


TEST_TOKEN = "test-token-not-a-real-secret"
TEST_SIGNING_KEY = "test-signing-key-not-real"
BASE_URL_8081 = "http://127.0.0.1:8081"
BASE_URL_18081 = "http://127.0.0.1:18081"
BASE_URL_8091 = "http://127.0.0.1:8091"


@override_settings(
    MANAGER_BASE_URL="",
    MANAGER_TOKEN="",
    MANAGER_SIGNING_KEY="",
    MANAGER_CONNECT_TIMEOUT=2.0,
    MANAGER_READ_TIMEOUT=5.0,
)
class ManagerClientConfigTest(TestCase):
    def test_config_defaults_to_disabled(self):
        config = manager_client.get_manager_config()
        self.assertFalse(config.enabled)
        self.assertEqual(config.base_url, "")
        self.assertEqual(config.connect_timeout, 2.0)
        self.assertEqual(config.read_timeout, 5.0)

    def test_disabled_when_url_is_missing(self):
        with override_settings(MANAGER_TOKEN=TEST_TOKEN):
            config = manager_client.get_manager_config()
        self.assertFalse(config.enabled)

    def test_disabled_when_token_is_missing(self):
        with override_settings(MANAGER_BASE_URL=BASE_URL_18081):
            config = manager_client.get_manager_config()
        self.assertFalse(config.enabled)

    def test_enabled_with_valid_configuration(self):
        with override_settings(MANAGER_BASE_URL=BASE_URL_18081, MANAGER_TOKEN=TEST_TOKEN):
            config = manager_client.get_manager_config()
        self.assertTrue(config.enabled)
        self.assertEqual(config.base_url, BASE_URL_18081)
        self.assertEqual(config.token, TEST_TOKEN)

    def test_config_reads_custom_timeouts(self):
        with override_settings(
            MANAGER_BASE_URL=BASE_URL_18081,
            MANAGER_TOKEN=TEST_TOKEN,
            MANAGER_CONNECT_TIMEOUT=1.5,
            MANAGER_READ_TIMEOUT=3.5,
        ):
            config = manager_client.get_manager_config()
        self.assertEqual(config.connect_timeout, 1.5)
        self.assertEqual(config.read_timeout, 3.5)

    def test_no_credentials_exposed_in_config_repr(self):
        with override_settings(
            MANAGER_BASE_URL=BASE_URL_18081,
            MANAGER_TOKEN=TEST_TOKEN,
            MANAGER_SIGNING_KEY=TEST_SIGNING_KEY,
        ):
            config = manager_client.get_manager_config()
        rendered = repr(config)
        self.assertNotIn(TEST_TOKEN, rendered)
        self.assertNotIn(TEST_SIGNING_KEY, rendered)


class ManagerClientValidationTest(TestCase):
    def _client(self, base_url):
        return manager_client.ManagerClient(
            manager_client.ManagerClientConfig(base_url=base_url, token=TEST_TOKEN, enabled=True)
        )

    def test_allowed_loopback_ports_are_accepted(self):
        for base_url in (BASE_URL_8081, BASE_URL_18081, BASE_URL_8091):
            with self.subTest(base_url=base_url):
                self._client(base_url)._validate_base_url()

    def test_localhost_and_ipv6_loopback_accepted(self):
        self._client("http://localhost:8091")._validate_base_url()
        self._client("http://[::1]:8091")._validate_base_url()

    def test_unsupported_port_is_rejected(self):
        for port in (80, 443, 8000, 9999):
            with self.subTest(port=port):
                with self.assertRaises(manager_client.ManagerError):
                    self._client(f"http://127.0.0.1:{port}")._validate_base_url()

    def test_public_and_private_addresses_rejected(self):
        for base_url in (
            "http://8.8.8.8:8091",
            "http://evil.com:8091",
            "http://192.168.1.100:8091",
            "http://10.0.0.5:8091",
        ):
            with self.subTest(base_url=base_url):
                with self.assertRaises(manager_client.ManagerError):
                    self._client(base_url)._validate_base_url()

    def test_https_credentials_query_fragment_path_rejected(self):
        bad = [
            "https://127.0.0.1:8091",
            "http://user:pass@127.0.0.1:8091",
            "http://127.0.0.1:8091/path",
            "http://127.0.0.1:8091?x=1",
            "http://127.0.0.1:8091#frag",
        ]
        for base_url in bad:
            with self.subTest(base_url=base_url):
                with self.assertRaises(manager_client.ManagerError):
                    self._client(base_url)._validate_base_url()


class ManagerClientRequestTest(TestCase):
    def _client(self):
        return manager_client.ManagerClient(
            manager_client.ManagerClientConfig(
                base_url=BASE_URL_8091,
                token=TEST_TOKEN,
                signing_key=TEST_SIGNING_KEY,
                connect_timeout=1.5,
                read_timeout=3.5,
                enabled=True,
            )
        )

    def test_bearer_authorization_header_is_constructed(self):
        headers = self._client()._headers({"instance_id": "1"}, idempotency_key="test-key")
        self.assertEqual(headers["Authorization"], f"Bearer {TEST_TOKEN}")
        self.assertEqual(headers["Idempotency-Key"], "test-key")
        self.assertIn("X-Runtime-Signature", headers)
        self.assertIn("X-Runtime-Timestamp", headers)

    def test_request_uses_configured_timeout_and_auth(self):
        response = Mock(status_code=200)
        response.json.return_value = {"status": "ok"}
        with patch("instances.manager_client.requests.request", return_value=response) as request_mock:
            result = self._client().health()
        self.assertEqual(result, {"status": "ok"})
        _, kwargs = request_mock.call_args
        self.assertEqual(kwargs["url"], f"{BASE_URL_8091}/v1/health")
        self.assertEqual(kwargs["timeout"], (1.5, 3.5))
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {TEST_TOKEN}")

    def test_timeout_is_reported_as_504(self):
        with patch("instances.manager_client.requests.request", side_effect=requests.exceptions.Timeout):
            with self.assertRaises(manager_client.ManagerError) as cm:
                self._client().health()
        self.assertEqual(cm.exception.status_code, 504)

    def test_connection_error_is_reported_as_503(self):
        with patch("instances.manager_client.requests.request", side_effect=requests.exceptions.ConnectionError):
            with self.assertRaises(manager_client.ManagerError) as cm:
                self._client().health()
        self.assertEqual(cm.exception.status_code, 503)

    def test_disabled_manager_never_sends_a_request(self):
        client = manager_client.ManagerClient(
            manager_client.ManagerClientConfig(base_url="", token="", enabled=False)
        )
        with patch("instances.manager_client.requests.request") as request_mock:
            with self.assertRaises(manager_client.ManagerError) as cm:
                client.health()
        self.assertEqual(cm.exception.status_code, 503)
        request_mock.assert_not_called()

    def test_legacy_contract_methods_remain_disabled(self):
        client = self._client()
        for method, args in (
            (client.provision, (1, 1, "test-catalog")),
            (client.inspect, (1,)),
            (client.stop, (1,)),
            (client.cleanup, (1,)),
        ):
            with self.subTest(method=method.__name__):
                with patch("instances.manager_client.requests.request") as request_mock:
                    with self.assertRaises(manager_client.ManagerError) as cm:
                        method(*args)
                self.assertEqual(cm.exception.status_code, 503)
                request_mock.assert_not_called()
