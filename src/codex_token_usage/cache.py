from __future__ import annotations

import os
import sqlite3
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


CacheMode = Literal["use", "rebuild", "disabled"]
CACHE_SCHEMA_VERSION = 6


@dataclass(frozen=True)
class CachedFile:
    path: str
    device: int
    inode: int
    source_size: int
    source_mtime_ns: int
    parsed_offset: int
    boundary_hash: str
    chunk_count: int


def cache_path(codex_home: Path) -> Path:
    return codex_home / ".cache" / "codex-token-usage" / "evidence-v1.sqlite3"


class SessionEvidenceCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> SessionEvidenceCache:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        self.connection = self._connect_with_recovery()
        self.connection.execute("BEGIN IMMEDIATE")
        self._ensure_schema()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        assert self.connection is not None
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()
            self.connection = None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=3)
        # This database is disposable derived data. Avoid durable-journal fsyncs,
        # which can be slower than rebuilding the cache on mounted home volumes.
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA busy_timeout=3000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _connect_with_recovery(self) -> sqlite3.Connection:
        try:
            connection = self._connect()
            connection.execute("PRAGMA schema_version").fetchone()
        except sqlite3.DatabaseError:
            try:
                connection.close()
            except UnboundLocalError:
                pass
            self.path.unlink(missing_ok=True)
            for suffix in ("-shm", "-wal"):
                self.path.with_name(self.path.name + suffix).unlink(missing_ok=True)
            connection = self._connect()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return connection

    def _ensure_schema(self) -> None:
        assert self.connection is not None
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row is not None and row[0] != str(CACHE_SCHEMA_VERSION):
            self.connection.execute("DROP TABLE IF EXISTS chunks")
            self.connection.execute("DROP TABLE IF EXISTS files")
            self.connection.execute("DELETE FROM metadata")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                device INTEGER NOT NULL,
                inode INTEGER NOT NULL,
                source_size INTEGER NOT NULL,
                source_mtime_ns INTEGER NOT NULL,
                parsed_offset INTEGER NOT NULL,
                boundary_hash TEXT NOT NULL,
                chunk_count INTEGER NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                path TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                evidence_blob BLOB NOT NULL,
                PRIMARY KEY(path, sequence),
                FOREIGN KEY(path) REFERENCES files(path) ON DELETE CASCADE
            )
            """
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
            (str(CACHE_SCHEMA_VERSION),),
        )

    def records(self) -> dict[str, CachedFile]:
        assert self.connection is not None
        rows = self.connection.execute(
            """
            SELECT path, device, inode, source_size, source_mtime_ns,
                   parsed_offset, boundary_hash, chunk_count
            FROM files
            """
        )
        return {row[0]: CachedFile(*row) for row in rows}

    def clear(self) -> None:
        assert self.connection is not None
        self.connection.execute("DELETE FROM chunks")
        self.connection.execute("DELETE FROM files")

    def upsert(self, record: CachedFile) -> None:
        assert self.connection is not None
        self.connection.execute(
            """
            INSERT INTO files(
                path, device, inode, source_size, source_mtime_ns,
                parsed_offset, boundary_hash, chunk_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                device = excluded.device,
                inode = excluded.inode,
                source_size = excluded.source_size,
                source_mtime_ns = excluded.source_mtime_ns,
                parsed_offset = excluded.parsed_offset,
                boundary_hash = excluded.boundary_hash,
                chunk_count = excluded.chunk_count
            """,
            (
                record.path,
                record.device,
                record.inode,
                record.source_size,
                record.source_mtime_ns,
                record.parsed_offset,
                record.boundary_hash,
                record.chunk_count,
            ),
        )

    def all_evidence_chunks(self) -> dict[str, list[tuple[int, str]]]:
        assert self.connection is not None
        chunks: dict[str, list[tuple[int, str]]] = {}
        for path, sequence, evidence_blob in self.connection.execute(
            "SELECT path, sequence, evidence_blob FROM chunks ORDER BY path, sequence"
        ):
            try:
                evidence_json = zlib.decompress(evidence_blob).decode("utf-8")
            except (TypeError, UnicodeDecodeError, zlib.error):
                evidence_json = ""
            chunks.setdefault(path, []).append(
                (int(sequence), evidence_json)
            )
        return chunks

    def replace_evidence(self, path: str, evidence_json: str) -> None:
        assert self.connection is not None
        self.connection.execute("DELETE FROM chunks WHERE path = ?", (path,))
        self.connection.execute(
            "INSERT INTO chunks(path, sequence, evidence_blob) VALUES(?, 0, ?)",
            (path, zlib.compress(evidence_json.encode("utf-8"), level=1)),
        )

    def append_evidence(self, path: str, sequence: int, evidence_json: str) -> None:
        assert self.connection is not None
        self.connection.execute(
            "INSERT OR REPLACE INTO chunks(path, sequence, evidence_blob) VALUES(?, ?, ?)",
            (path, sequence, zlib.compress(evidence_json.encode("utf-8"), level=1)),
        )

    def remove_missing(self, current_paths: set[str]) -> int:
        assert self.connection is not None
        cached_paths = {row[0] for row in self.connection.execute("SELECT path FROM files")}
        missing = cached_paths - current_paths
        self.connection.executemany("DELETE FROM files WHERE path = ?", ((path,) for path in missing))
        return len(missing)
