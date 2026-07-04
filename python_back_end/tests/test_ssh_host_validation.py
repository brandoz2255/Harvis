"""Host-profile validation invariants for the Phase 7 SSH scaffold.

These pure functions (remote/validation.py — stdlib-only, importable without
FastAPI) are the security boundary for anything that could one day reach an SSH
command line, so the rules locked down here are:

  1. Shell metacharacters, whitespace, and control characters NEVER validate as
     part of a host string (injection guard).
  2. A leading '-' never validates (ssh option-injection guard, e.g. -oProxyCommand).
  3. Scheme / userinfo / embedded port are rejected — the host field is a BARE
     hostname or IP only.
  4. Legit RFC 1123 hostnames and literal IPv4/IPv6 addresses pass.
  5. Port and username validators enforce sane ranges/charsets.

Run: ``python3 -m unittest tests.test_ssh_host_validation`` from python_back_end/.
"""

import unittest

from remote.validation import (
    validate_host_string,
    validate_port,
    validate_profile_name,
    validate_username,
)


class TestHostStringValid(unittest.TestCase):
    def test_valid_hostnames_and_ips(self):
        for host in (
            "localhost",
            "printer-01",
            "octopi.local",
            "my-nas.home.arpa",
            "sub.domain.example.com",
            "example.com.",  # FQDN trailing dot
            "192.168.1.50",
            "10.0.0.1",
            "2001:db8::1",
            "::1",
            "a" * 63 + ".example.com",  # max-length label
        ):
            ok, reason = validate_host_string(host)
            self.assertTrue(ok, f"{host!r} should validate, got: {reason}")


class TestHostStringInjectionGuards(unittest.TestCase):
    def test_shell_metacharacters_rejected(self):
        for host in (
            "host;rm -rf /",
            "host|cat /etc/passwd",
            "host&&whoami",
            "host$(id)",
            "host`id`",
            "host>out",
            "host<in",
            "host'quote",
            'host"quote',
            "host*glob",
            "host?glob",
            "host{brace}",
            "host(paren)",
            "host[bracket]",
            "host!bang",
            "host~tilde",
            "host\\backslash",
            "host,comma",
        ):
            ok, _ = validate_host_string(host)
            self.assertFalse(ok, f"{host!r} must be rejected")

    def test_whitespace_and_control_chars_rejected(self):
        for host in ("host name", "host\tname", "host\nname", "host\rname", "host\x00", " host", "host "):
            ok, _ = validate_host_string(host)
            self.assertFalse(ok, f"{host!r} must be rejected")

    def test_option_injection_leading_dash_rejected(self):
        ok, _ = validate_host_string("-oProxyCommand=payload")
        self.assertFalse(ok)

    def test_scheme_userinfo_and_port_rejected(self):
        for host in ("ssh://host", "http://host", "root@host", "host:22", "host:2222"):
            ok, _ = validate_host_string(host)
            self.assertFalse(ok, f"{host!r} must be rejected")

    def test_empty_nonstring_and_overlong_rejected(self):
        self.assertFalse(validate_host_string("")[0])
        self.assertFalse(validate_host_string("   ")[0])
        self.assertFalse(validate_host_string(None)[0])
        self.assertFalse(validate_host_string(42)[0])
        self.assertFalse(validate_host_string("a" * 254)[0])

    def test_malformed_hostnames_rejected(self):
        for host in ("-leadinghyphen.com", "trailing-.com", "double..dot", ".leadingdot", "under_score.com"):
            ok, _ = validate_host_string(host)
            self.assertFalse(ok, f"{host!r} must be rejected")


class TestPortValidation(unittest.TestCase):
    def test_valid_ports(self):
        for port in (1, 22, 2222, 65535):
            self.assertTrue(validate_port(port)[0], f"{port} should validate")

    def test_invalid_ports(self):
        for port in (0, -1, 65536, "22", 22.0, None, True):
            self.assertFalse(validate_port(port)[0], f"{port!r} must be rejected")


class TestUsernameValidation(unittest.TestCase):
    def test_valid_usernames(self):
        for name in ("pi", "root", "deploy_user", "harvis-bot", "user.name", "_svc", "A" * 32):
            self.assertTrue(validate_username(name)[0], f"{name!r} should validate")

    def test_invalid_usernames(self):
        for name in ("", "1leadingdigit", "user name", "user;id", "user$", "-flag", "a" * 33, None):
            self.assertFalse(validate_username(name)[0], f"{name!r} must be rejected")


class TestProfileNameValidation(unittest.TestCase):
    def test_valid_names(self):
        for name in ("Home NAS", "octopi (garage)", "printer #1", "x" * 64):
            self.assertTrue(validate_profile_name(name)[0], f"{name!r} should validate")

    def test_invalid_names(self):
        for name in ("", "   ", "x" * 65, "bad\x00name", "bad\nname", None, 7):
            self.assertFalse(validate_profile_name(name)[0], f"{name!r} must be rejected")


if __name__ == "__main__":
    unittest.main()
