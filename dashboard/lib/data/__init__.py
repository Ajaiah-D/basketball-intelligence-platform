"""The dashboard's read-only data access, one module per domain.

core holds the connection, the caches and the warehouse location; the
domain modules (seasons, players, teams, games, advanced, finances,
predictions, arcade, diagnosis, schedule) are plain SQL over the dbt marts
that return the column names the views show. Nothing here imports ml or
scripts: the deployed app installs neither's dependencies.
"""
