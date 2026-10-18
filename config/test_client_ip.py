from django.test import RequestFactory, SimpleTestCase, override_settings

from .client_ip import InvalidClientAddress, client_ip


@override_settings(TRUST_PROXY_CLIENT_IP=False)
class ClientAddressTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, peer="203.0.113.10", **headers):
        return self.factory.post("/", REMOTE_ADDR=peer, **headers)

    def test_default_ignores_forwarded_headers_even_from_a_private_peer(self):
        for peer in ("203.0.113.10", "127.0.0.1", "172.18.0.1", "fd00::1"):
            with self.subTest(peer=peer):
                self.assertEqual(client_ip(self.request(
                    peer, HTTP_X_FORWARDED_FOR="198.51.100.20", HTTP_X_REAL_IP="198.51.100.30",
                    HTTP_FORWARDED="for=198.51.100.40",
                )), peer)

    @override_settings(TRUST_PROXY_CLIENT_IP=True)
    def test_explicit_trust_accepts_one_client_from_private_or_loopback_proxy(self):
        for peer in ("127.0.0.1", "10.0.0.3", "172.18.0.1", "192.168.2.1", "::1", "fd00::1", "::ffff:172.18.0.1"):
            with self.subTest(peer=peer):
                self.assertEqual(client_ip(self.request(peer, HTTP_X_FORWARDED_FOR="203.0.113.20")), "203.0.113.20")

    @override_settings(TRUST_PROXY_CLIENT_IP=True)
    def test_trust_flag_does_not_accept_headers_from_public_or_unspecified_peer(self):
        for peer in ("8.8.8.8", "203.0.113.10", "2001:4860:4860::8888", "0.0.0.0", "::", "invalid", ""):
            with self.subTest(peer=peer), self.assertRaises(InvalidClientAddress):
                client_ip(self.request(peer, HTTP_X_FORWARDED_FOR="198.51.100.20"))

    @override_settings(TRUST_PROXY_CLIENT_IP=True)
    def test_missing_or_ambiguous_forwarded_address_has_no_shared_fallback(self):
        values = (
            None, "", "unknown", "203.0.113.1, 203.0.113.2", "203.0.113.1:1234",
            "[2001:db8::1]:443", "fe80::1%eth0", "for=203.0.113.1",
            "203.0.113.1\r\n", "0.0.0.0", "::", "ff02::1", "224.0.0.1",
            "000.000.000.001", "a" * 100,
        )
        for value in values:
            headers = {} if value is None else {"HTTP_X_FORWARDED_FOR": value}
            with self.subTest(value=value), self.assertRaises(InvalidClientAddress):
                client_ip(self.request("172.18.0.1", **headers))

    def test_canonical_addresses_prevent_textual_aliases_from_splitting_buckets(self):
        self.assertEqual(client_ip(self.request("2001:0DB8:0000:0000:0000:0000:0000:0001")), "2001:db8::1")
        self.assertEqual(client_ip(self.request("::ffff:192.0.2.1")), "192.0.2.1")
        with self.settings(TRUST_PROXY_CLIENT_IP=True):
            self.assertEqual(client_ip(self.request("::1", HTTP_X_FORWARDED_FOR=" ::ffff:192.0.2.1 ")), "192.0.2.1")

    def test_invalid_direct_peer_cannot_fall_back_to_user_header(self):
        for peer in ("", None, "not-an-ip"):
            with self.subTest(peer=peer), self.assertRaises(InvalidClientAddress):
                client_ip(self.request(peer, HTTP_X_FORWARDED_FOR="203.0.113.1"))
