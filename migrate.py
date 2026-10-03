"""Safe additive migration of the existing SQLite archive. No inference."""
from database import init_db
from pipeline import register_sources, normalize_legacy_urls
if __name__ == "__main__":
    init_db()
    register_sources()
    normalize_legacy_urls()
    print("Additive migration complete; historical articles preserved.")
