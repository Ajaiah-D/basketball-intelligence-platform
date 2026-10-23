"""Shared plumbing for the pipeline and the dashboard: where data lives,
how files are written, team facts, seasons, formatting and the shared
numbers. Standard library plus python-dotenv only (pandas and pyarrow in
core/io.py alone), so the deployed dashboard can import it;
tests/test_import_boundaries.py holds it to that."""
