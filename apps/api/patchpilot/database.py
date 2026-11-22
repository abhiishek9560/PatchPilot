from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class PostgresConnection:
    """Small DB-API compatibility layer for the existing parameterized SQL."""

    def __init__(self, database_url: str) -> None:
        import psycopg
        from psycopg.rows import dict_row

        self._connection = psycopg.connect(database_url, row_factory=dict_row)

    def __enter__(self) -> PostgresConnection:
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool | None:
        return self._connection.__exit__(exc_type, exc, traceback)

    @staticmethod
    def _query(sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql: str, parameters: Sequence[object] = ()) -> Any:
        return self._connection.execute(self._query(sql), parameters)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self._connection.execute(statement)
