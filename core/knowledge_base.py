"""Local SQLite knowledge base for Agent retrieval."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import zipfile
from contextlib import contextmanager
from datetime import datetime
from html import unescape
from pathlib import Path
from xml.etree import ElementTree

from .paths import _base_dir


DB_FILE = _base_dir() / "knowledge_base.sqlite3"
SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".json", ".csv", ".log", ".py", ".docx"}


class KnowledgeBaseManager:
    """Small local KB backed by SQLite FTS5.

    It intentionally avoids external services and heavyweight dependencies so the
    packaged app can run on another machine without provisioning a vector DB.
    """

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_FILE
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kb_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kb_id INTEGER NOT NULL,
                    doc_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
                )
                """
            )
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                    USING fts5(content, kb_id UNINDEXED, doc_id UNINDEXED, chunk_id UNINDEXED)
                    """
                )
            except sqlite3.OperationalError:
                pass

    def create_knowledge_base(self, name: str, description: str = "") -> int:
        name = self._clean_name(name)
        if not name:
            raise ValueError("知识库名称不能为空")
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO knowledge_bases (name, description, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET description=excluded.description
                """,
                (name, description.strip(), now),
            )
            row = conn.execute(
                "SELECT id FROM knowledge_bases WHERE name = ?", (name,)
            ).fetchone()
            return int(row["id"] if row else cur.lastrowid)

    def list_knowledge_bases(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT kb.id, kb.name, kb.description, kb.created_at,
                       COUNT(DISTINCT d.id) AS document_count,
                       COUNT(c.id) AS chunk_count
                FROM knowledge_bases kb
                LEFT JOIN documents d ON d.kb_id = kb.id
                LEFT JOIN chunks c ON c.kb_id = kb.id
                GROUP BY kb.id
                ORDER BY kb.created_at DESC, kb.id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_knowledge_base(self, kb_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, description, created_at FROM knowledge_bases WHERE id = ?",
                (kb_id,),
            ).fetchone()
        return dict(row) if row else None

    def import_file(self, kb_id: int, path: str | Path) -> dict:
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(str(file_path))
        if file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError(f"暂不支持该文件类型: {file_path.suffix}")

        text = self._read_file_text(file_path)
        chunks = self._chunk_text(text)
        if not chunks:
            raise ValueError("未读取到可导入的文本内容")

        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cur = conn.execute(
                """
                INSERT INTO documents (kb_id, title, source_path, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (kb_id, file_path.name, str(file_path), now),
            )
            doc_id = int(cur.lastrowid)
            for idx, chunk in enumerate(chunks):
                cur = conn.execute(
                    """
                    INSERT INTO chunks (kb_id, doc_id, chunk_index, content)
                    VALUES (?, ?, ?, ?)
                    """,
                    (kb_id, doc_id, idx, chunk),
                )
                chunk_id = int(cur.lastrowid)
                try:
                    conn.execute(
                        """
                        INSERT INTO chunks_fts (content, kb_id, doc_id, chunk_id)
                        VALUES (?, ?, ?, ?)
                        """,
                        (chunk, kb_id, doc_id, chunk_id),
                    )
                except sqlite3.OperationalError:
                    pass
        return {"document_id": doc_id, "chunk_count": len(chunks), "title": file_path.name}

    def search(self, kb_id: int, query: str, limit: int = 5) -> list[dict]:
        query = query.strip()
        if not query:
            return []
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT c.id, c.content, d.title, d.source_path,
                           bm25(chunks_fts) AS score
                    FROM chunks_fts
                    JOIN chunks c ON c.id = chunks_fts.chunk_id
                    JOIN documents d ON d.id = c.doc_id
                    WHERE chunks_fts MATCH ? AND chunks_fts.kb_id = ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (self._fts_query(query), kb_id, limit),
                ).fetchall()
                if rows:
                    return [dict(row) for row in rows]
            except sqlite3.OperationalError:
                pass

            terms = [term for term in re.split(r"\s+", query) if term]
            if not terms:
                terms = [query]
            where = " OR ".join("c.content LIKE ?" for _ in terms)
            params = [f"%{term}%" for term in terms]
            rows = conn.execute(
                f"""
                SELECT c.id, c.content, d.title, d.source_path, 0 AS score
                FROM chunks c
                JOIN documents d ON d.id = c.doc_id
                WHERE c.kb_id = ? AND ({where})
                LIMIT ?
                """,
                [kb_id, *params, limit],
            ).fetchall()
        return [dict(row) for row in rows]

    def _read_file_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".docx":
            return self._read_docx(path)
        if suffix == ".json":
            with path.open("r", encoding="utf-8-sig") as f:
                data = json.load(f)
            return json.dumps(data, ensure_ascii=False, indent=2)
        if suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                return "\n".join(" | ".join(row) for row in csv.reader(f))
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(errors="ignore")

    def _read_docx(self, path: Path) -> str:
        parts: list[str] = []
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        for para in root.findall(".//w:p", ns):
            text = "".join(node.text or "" for node in para.findall(".//w:t", ns))
            if text.strip():
                parts.append(text.strip())
        return "\n".join(parts)

    def _chunk_text(self, text: str, size: int = 900, overlap: int = 120) -> list[str]:
        normalized = unescape(text).replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
        if not normalized:
            return []
        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(len(normalized), start + size)
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            start = max(0, end - overlap)
        return chunks

    def _fts_query(self, query: str) -> str:
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", query)
        return " OR ".join(tokens) if tokens else query

    def _clean_name(self, name: str) -> str:
        return re.sub(r"\s+", " ", name).strip()
