import os

# Must be set before any app module import so pydantic-settings can validate Settings.
os.environ.setdefault("SECRET_KEY", "test-secret-not-for-production")
