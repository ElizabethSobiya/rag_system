import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from app.core.config import normalize_database_url


class NormalizeDatabaseUrlTests(unittest.TestCase):
    def test_leaves_a_correctly_specified_url_untouched(self):
        url = "postgresql+asyncpg://raguser:ragpassword@localhost:5432/ragdb"
        self.assertEqual(normalize_database_url(url), url)

    def test_adds_the_asyncpg_driver_to_a_bare_postgresql_url(self):
        self.assertEqual(
            normalize_database_url("postgresql://u:p@db.example.com:5432/postgres"),
            "postgresql+asyncpg://u:p@db.example.com:5432/postgres",
        )

    def test_upgrades_the_legacy_postgres_scheme(self):
        self.assertEqual(
            normalize_database_url("postgres://u:p@db.example.com:5432/postgres"),
            "postgresql+asyncpg://u:p@db.example.com:5432/postgres",
        )

    def test_translates_sslmode_into_the_asyncpg_spelling(self):
        # asyncpg raises TypeError on `sslmode`, so a pasted managed-provider URL
        # would otherwise fail on the first connection.
        self.assertEqual(
            normalize_database_url(
                "postgresql://u:p@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
                "?sslmode=require"
            ),
            "postgresql+asyncpg://u:p@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
            "?ssl=require",
        )

    def test_maps_verifying_sslmodes_onto_require(self):
        self.assertEqual(
            normalize_database_url("postgresql://u:p@h/db?sslmode=verify-full"),
            "postgresql+asyncpg://u:p@h/db?ssl=require",
        )

    def test_preserves_a_request_for_no_tls(self):
        self.assertEqual(
            normalize_database_url("postgresql://u:p@h/db?sslmode=disable"),
            "postgresql+asyncpg://u:p@h/db?ssl=disable",
        )

    def test_drops_parameters_asyncpg_cannot_accept(self):
        self.assertEqual(
            normalize_database_url(
                "postgresql://u:p@h/db?channel_binding=require&sslrootcert=/ca.crt"
            ),
            "postgresql+asyncpg://u:p@h/db",
        )

    def test_keeps_parameters_that_are_not_libpq_specific(self):
        self.assertEqual(
            normalize_database_url("postgresql://u:p@h/db?application_name=rag"),
            "postgresql+asyncpg://u:p@h/db?application_name=rag",
        )

    def test_an_explicit_ssl_argument_wins_over_sslmode(self):
        self.assertEqual(
            normalize_database_url("postgresql://u:p@h/db?sslmode=require&ssl=prefer"),
            "postgresql+asyncpg://u:p@h/db?ssl=prefer",
        )

    def test_leaves_an_explicitly_chosen_other_driver_alone(self):
        url = "postgresql+psycopg://u:p@h/db?sslmode=require"
        self.assertEqual(normalize_database_url(url), url)

    def test_does_not_mangle_a_password_containing_url_metacharacters(self):
        url = "postgresql://u:p%40ss%2Fword@h:5432/db"
        self.assertEqual(
            normalize_database_url(url),
            "postgresql+asyncpg://u:p%40ss%2Fword@h:5432/db",
        )


if __name__ == "__main__":
    unittest.main()
