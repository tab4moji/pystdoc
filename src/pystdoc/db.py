"""SQLite storage manager for Docgen: manages file/symbol hashes and cache."""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pystdoc.symbols import Symbol


class DocgenDB:
    """Thread-safe SQLite DB manager for hashes, metadata, and LLM cache."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(
            str(self.db_path), timeout=60.0, check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Initialize tables and indexes with WAL mode."""
        with self.lock:
            with self.conn:
                self.conn.execute("PRAGMA journal_mode=WAL;")
                self.conn.execute("PRAGMA synchronous=NORMAL;")
                self.conn.execute("PRAGMA busy_timeout=60000;")

                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS file_hashes (
                        rel_path TEXT PRIMARY KEY,
                        file_hash TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS symbol_hashes (
                        unique_id TEXT PRIMARY KEY,
                        rel_path TEXT NOT NULL,
                        symbol_hash TEXT NOT NULL,
                        logic_hash TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                try:
                    self.conn.execute(
                        "ALTER TABLE symbol_hashes ADD COLUMN logic_hash TEXT;"
                    )
                except Exception:
                    pass

                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS symbol_cache (
                        unique_id TEXT PRIMARY KEY,
                        purpose TEXT,
                        inputs_note TEXT,
                        outputs_note TEXT,
                        overview TEXT,
                        top_down_context TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS design_cache (
                        target_key TEXT PRIMARY KEY,
                        input_hash TEXT NOT NULL,
                        content TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS symbols_metadata (
                        unique_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        fqdn TEXT,
                        rel_path TEXT NOT NULL,
                        line_start INTEGER,
                        line_end INTEGER,
                        signature TEXT,
                        callees_json TEXT,
                        referencing_funcs_json TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

    def update_file_hash(self, rel_path: str, current_hash: str) -> bool:
        """Update file hash and return whether it changed."""
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT file_hash FROM file_hashes WHERE rel_path = ?",
                (rel_path,),
            )
            row = cur.fetchone()
            previous_hash = row["file_hash"] if row else None
            is_changed = previous_hash != current_hash

            if is_changed:
                with self.conn:
                    self.conn.execute(
                        """
                        INSERT INTO file_hashes (
                            rel_path, file_hash, updated_at
                        )
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(rel_path) DO UPDATE SET
                            file_hash=excluded.file_hash,
                            updated_at=CURRENT_TIMESTAMP;
                    """,
                        (rel_path, current_hash),
                    )
            return is_changed

    def update_symbol_hash(
        self,
        unique_id: str,
        rel_path: str,
        current_sym_hash: str,
        current_logic_hash: Optional[str] = None,
    ) -> Tuple[bool, bool]:
        """Update symbol hashes and return (is_full_changed,
        is_logic_changed)."""
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT symbol_hash, logic_hash FROM symbol_hashes "
                "WHERE unique_id = ?",
                (unique_id,),
            )
            row = cur.fetchone()
            previous_full = row["symbol_hash"] if row else None
            previous_logic = None
            if row and "logic_hash" in row.keys():
                previous_logic = row["logic_hash"]

            is_full_changed = previous_full != current_sym_hash

            if previous_full is None:
                is_logic_changed = True
            elif current_logic_hash is not None and previous_logic is not None:
                is_logic_changed = previous_logic != current_logic_hash
            elif current_logic_hash is not None and previous_logic is None:
                is_logic_changed = True
            else:
                is_logic_changed = is_full_changed

            if is_full_changed or (
                current_logic_hash is not None
                and previous_logic != current_logic_hash
            ):
                with self.conn:
                    self.conn.execute(
                        """
                        INSERT INTO symbol_hashes (
                            unique_id, rel_path, symbol_hash,
                            logic_hash, updated_at
                        )
                        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(unique_id) DO UPDATE SET
                            symbol_hash=excluded.symbol_hash,
                            logic_hash=excluded.logic_hash,
                            updated_at=CURRENT_TIMESTAMP;
                    """,
                        (
                            unique_id,
                            rel_path,
                            current_sym_hash,
                            current_logic_hash,
                        ),
                    )
            return is_full_changed, is_logic_changed

    def save_symbol_cache(self, unique_id: str, data: Dict[str, Any]) -> None:
        """Save symbol LLM analysis result to SQLite with immediate commit."""
        with self.lock:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO symbol_cache (
                        unique_id, purpose, inputs_note, outputs_note,
                        overview, top_down_context, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(unique_id) DO UPDATE SET
                        purpose=excluded.purpose,
                        inputs_note=excluded.inputs_note,
                        outputs_note=excluded.outputs_note,
                        overview=excluded.overview,
                        top_down_context=excluded.top_down_context,
                        updated_at=CURRENT_TIMESTAMP;
                """,
                    (
                        unique_id,
                        data.get("purpose", ""),
                        data.get("inputs_note", ""),
                        data.get("outputs_note", ""),
                        data.get("overview", ""),
                        data.get("top_down_context", ""),
                    ),
                )

    def load_symbol_cache(self, unique_id: str) -> Optional[Dict[str, Any]]:
        """Load symbol LLM analysis result from SQLite."""
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                SELECT purpose, inputs_note, outputs_note, overview,
                       top_down_context
                FROM symbol_cache WHERE unique_id = ?
            """,
                (unique_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "purpose": row["purpose"] or "",
                    "inputs_note": row["inputs_note"] or "",
                    "outputs_note": row["outputs_note"] or "",
                    "overview": row["overview"] or "",
                    "top_down_context": row["top_down_context"] or "",
                }
            return None

    def load_design_cache(
        self, target_key: str, current_input_hash: str
    ) -> Optional[str]:
        """Load cached design document if input hash matches."""
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                SELECT content FROM design_cache
                WHERE target_key = ? AND input_hash = ?
            """,
                (target_key, current_input_hash),
            )
            row = cur.fetchone()
            if row:
                return row["content"]
            return None

    def save_design_cache(
        self, target_key: str, input_hash: str, content: str
    ) -> None:
        """Save design doc content and input hash with immediate commit."""
        with self.lock:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO design_cache (
                        target_key, input_hash, content, updated_at
                    )
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(target_key) DO UPDATE SET
                        input_hash=excluded.input_hash,
                        content=excluded.content,
                        updated_at=CURRENT_TIMESTAMP;
                """,
                    (target_key, input_hash, content),
                )

    def save_symbol_metadata(
        self, unique_id: str, sym: Symbol, rel_path: str
    ) -> None:
        """Save symbol structural metadata to SQLite."""
        with self.lock:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO symbols_metadata (
                        unique_id, name, kind, fqdn, rel_path, line_start,
                        line_end, signature, callees_json,
                        referencing_funcs_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(unique_id) DO UPDATE SET
                        name=excluded.name,
                        kind=excluded.kind,
                        fqdn=excluded.fqdn,
                        rel_path=excluded.rel_path,
                        line_start=excluded.line_start,
                        line_end=excluded.line_end,
                        signature=excluded.signature,
                        callees_json=excluded.callees_json,
                        referencing_funcs_json=excluded.referencing_funcs_json,
                        updated_at=CURRENT_TIMESTAMP;
                """,
                    (
                        unique_id,
                        sym.name,
                        sym.kind,
                        sym.fqdn,
                        rel_path,
                        sym.line_start,
                        sym.line_end,
                        sym.signature,
                        json.dumps(sym.callees, ensure_ascii=False),
                        json.dumps(sym.referencing_functions,
                                   ensure_ascii=False),
                    ),
                )

    def load_symbol_metadata(
        self, unique_id: str
    ) -> Optional[Dict[str, Any]]:
        """Load single symbol metadata from SQLite."""
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                SELECT unique_id, name, kind, fqdn, rel_path, line_start,
                       line_end, signature, callees_json,
                       referencing_funcs_json
                FROM symbols_metadata WHERE unique_id = ?
            """,
                (unique_id,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
            return None

    def get_all_files(self) -> List[str]:
        """Return list of all indexed file relative paths."""
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT rel_path FROM file_hashes ORDER BY rel_path")
            return [row["rel_path"] for row in cur.fetchall()]

    def get_all_symbols_metadata(self) -> List[Dict[str, Any]]:
        """Return metadata for all indexed symbols ordered by file and line."""
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("""
                SELECT unique_id, name, kind, fqdn, rel_path, line_start,
                       line_end, signature, callees_json,
                       referencing_funcs_json
                FROM symbols_metadata
                ORDER BY rel_path, line_start
            """)
            return [dict(row) for row in cur.fetchall()]

    def find_symbols_by_query(self, query: str) -> List[Dict[str, Any]]:
        """Search symbol metadata by exact FQDN/name, suffix, or substring."""
        clean_query = query.strip()
        dot_query = clean_query.replace("::", ".")
        with self.lock:
            cur = self.conn.cursor()
            # 1. Exact match by unique_id, name, fqdn, or dot_query
            cur.execute("""
                SELECT unique_id, name, kind, fqdn, rel_path, line_start,
                       line_end, signature, callees_json,
                       referencing_funcs_json
                FROM symbols_metadata
                WHERE unique_id = ? OR fqdn = ? OR fqdn = ? OR name = ?
                ORDER BY rel_path, line_start
            """, (clean_query, clean_query, dot_query, clean_query))
            rows = [dict(r) for r in cur.fetchall()]
            if rows:
                return rows

            # 2. Suffix match (e.g. searching 'main' matches 'Userlib.main')
            cur.execute("""
                SELECT unique_id, name, kind, fqdn, rel_path, line_start,
                       line_end, signature, callees_json,
                       referencing_funcs_json
                FROM symbols_metadata
                WHERE fqdn LIKE ? OR fqdn LIKE ?
                ORDER BY rel_path, line_start
            """, (f"%.{dot_query}", f"%::{clean_query}"))
            rows = [dict(r) for r in cur.fetchall()]
            if rows:
                return rows

            # 3. Case-insensitive substring match
            cur.execute("""
                SELECT unique_id, name, kind, fqdn, rel_path, line_start,
                       line_end, signature, callees_json,
                       referencing_funcs_json
                FROM symbols_metadata
                WHERE LOWER(fqdn) LIKE ? OR LOWER(name) LIKE ?
                ORDER BY rel_path, line_start
            """, (f"%{dot_query.lower()}%", f"%{clean_query.lower()}%"))
            return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        """Close SQLite connection."""
        with self.lock:
            if self.conn:
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None

    def __enter__(self) -> "DocgenDB":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()
