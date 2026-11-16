from posmon.domain.normalize import (
    MATCH_DOMAIN,
    MATCH_EXACT_HOST,
    host_matches,
    normalize_host,
    registrable_base,
)


class TestNormalizeHost:
    def test_strips_scheme_path_query_case(self):
        assert normalize_host("https://www.Example.RU/page?x=1") == "www.example.ru"

    def test_trailing_slash_and_dot(self):
        assert normalize_host("http://example.ru/") == "example.ru"
        assert normalize_host("example.ru.") == "example.ru"

    def test_bare_host(self):
        assert normalize_host("example.ru") == "example.ru"
        assert normalize_host("sub.example.ru") == "sub.example.ru"

    def test_port_and_userinfo(self):
        assert normalize_host("http://user:pass@example.ru:8080/x") == "example.ru"

    def test_empty(self):
        assert normalize_host("") == ""
        assert normalize_host("   ") == ""


class TestRegistrableBase:
    def test_strips_leading_www(self):
        assert registrable_base("https://www.example.ru") == "example.ru"
        assert registrable_base("example.ru") == "example.ru"

    def test_keeps_subdomain(self):
        # sub != www, поддомен не является базой
        assert registrable_base("sub.example.ru") == "sub.example.ru"


class TestHostMatchesDomainMode:
    def test_same_domain(self):
        assert host_matches("https://example.ru/page", "example.ru", MATCH_DOMAIN)

    def test_www_variant(self):
        assert host_matches("https://www.example.ru", "example.ru", MATCH_DOMAIN)
        assert host_matches("https://example.ru", "www.example.ru", MATCH_DOMAIN)

    def test_subdomain_included(self):
        assert host_matches("https://blog.example.ru/x", "example.ru", MATCH_DOMAIN)

    def test_no_false_prefix_match(self):
        assert not host_matches("https://notexample.ru", "example.ru", MATCH_DOMAIN)

    def test_no_false_suffix_match(self):
        assert not host_matches("https://example.ru.evil.com", "example.ru", MATCH_DOMAIN)


class TestHostMatchesExactHost:
    def test_exact_only(self):
        assert host_matches("https://www.example.ru/x", "www.example.ru", MATCH_EXACT_HOST)

    def test_subdomain_excluded(self):
        assert not host_matches("https://blog.example.ru", "www.example.ru", MATCH_EXACT_HOST)

    def test_apex_excluded_when_www_required(self):
        assert not host_matches("https://example.ru", "www.example.ru", MATCH_EXACT_HOST)
