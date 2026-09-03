"""CORS_ORIGINS arrives as a dashboard string, so parsing must not crash the process.

Typing the setting as a list made pydantic-settings json.loads it inside the
settings source, which raises SettingsError at import and exits the container
before it can serve anything — including /health, so the failure looked like a
database problem rather than a malformed environment variable.
"""

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from app.core.config import Settings, parse_cors_origins


class ParseCorsOriginsTests(unittest.TestCase):
    def test_parses_the_json_array_the_deploy_docs_use(self):
        self.assertEqual(
            parse_cors_origins('["https://app.vercel.app"]'),
            ["https://app.vercel.app"],
        )

    def test_parses_a_json_array_of_several_origins(self):
        self.assertEqual(
            parse_cors_origins('["https://app.vercel.app", "https://www.example.com"]'),
            ["https://app.vercel.app", "https://www.example.com"],
        )

    def test_accepts_a_bare_origin_pasted_into_a_dashboard(self):
        self.assertEqual(
            parse_cors_origins("https://app.vercel.app"),
            ["https://app.vercel.app"],
        )

    def test_accepts_a_comma_separated_list(self):
        self.assertEqual(
            parse_cors_origins("https://a.vercel.app,https://b.vercel.app"),
            ["https://a.vercel.app", "https://b.vercel.app"],
        )

    def test_ignores_whitespace_around_comma_separated_entries(self):
        self.assertEqual(
            parse_cors_origins(" https://a.vercel.app , https://b.vercel.app "),
            ["https://a.vercel.app", "https://b.vercel.app"],
        )

    def test_strips_a_trailing_slash_that_would_never_match_an_origin_header(self):
        self.assertEqual(
            parse_cors_origins("https://app.vercel.app/"),
            ["https://app.vercel.app"],
        )
        self.assertEqual(
            parse_cors_origins('["https://app.vercel.app/"]'),
            ["https://app.vercel.app"],
        )

    def test_a_trailing_comma_does_not_produce_an_empty_origin(self):
        self.assertEqual(
            parse_cors_origins("https://a.vercel.app,"),
            ["https://a.vercel.app"],
        )

    def test_an_empty_value_means_no_cross_origin_callers(self):
        self.assertEqual(parse_cors_origins(""), [])
        self.assertEqual(parse_cors_origins("   "), [])

    def test_passes_a_wildcard_through_untouched(self):
        self.assertEqual(parse_cors_origins("*"), ["*"])

    def test_malformed_json_array_names_the_quoting_rule(self):
        # Single quotes are the common mistake and are not valid JSON.
        with self.assertRaisesRegex(ValueError, "double"):
            parse_cors_origins("['https://app.vercel.app']")


class SettingsCorsOriginsTests(unittest.TestCase):
    """The env var must reach `settings.cors_origins` without decoding at import."""

    def setUp(self):
        self._saved = os.environ.get("CORS_ORIGINS")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("CORS_ORIGINS", None)
        else:
            os.environ["CORS_ORIGINS"] = self._saved

    def test_reads_a_bare_origin_that_previously_exited_the_process(self):
        os.environ["CORS_ORIGINS"] = "https://app.vercel.app/"

        settings = Settings(_env_file=None)

        self.assertEqual(settings.cors_origins, ["https://app.vercel.app"])

    def test_defaults_to_localhost_when_unset(self):
        os.environ.pop("CORS_ORIGINS", None)

        settings = Settings(_env_file=None)

        self.assertEqual(
            settings.cors_origins,
            ["http://localhost:5173", "http://localhost:3000"],
        )
