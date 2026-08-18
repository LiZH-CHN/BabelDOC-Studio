"""
术语库管理模块
包含：GlossaryManager 类、GlossaryEntry 数据类
提供术语库的增删改查、导入导出功能
"""

import sqlite3
import json
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from gui.core.sqlite_utils import safe_sqlite_connect


@dataclass
class GlossaryEntry:
    """术语条目"""
    id: int = 0
    term: str = ""
    translation: str = ""
    lang_in: str = ""
    lang_out: str = ""
    domain: str = ""
    description: str = ""
    case_sensitive: bool = False
    created_at: float = 0.0


class GlossaryManager:
    """术语库管理器"""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "data" / "translation_memory.db"
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        with safe_sqlite_connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS glossary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT NOT NULL,
                    translation TEXT NOT NULL,
                    lang_in TEXT NOT NULL,
                    lang_out TEXT NOT NULL,
                    domain TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    case_sensitive INTEGER DEFAULT 0,
                    created_at REAL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_glossary_term ON glossary(term);
                CREATE INDEX IF NOT EXISTS idx_glossary_lang ON glossary(lang_in, lang_out);
            """)

    def add_term(self, term: str, translation: str, lang_in: str, lang_out: str,
                 domain: str = "", description: str = "", case_sensitive: bool = False) -> bool:
        """添加术语"""
        if not term.strip() or not translation.strip():
            return False

        try:
            with safe_sqlite_connect(self.db_path) as conn:
                # 检查是否已存在
                cursor = conn.execute(
                    "SELECT id FROM glossary WHERE term = ? AND lang_in = ? AND lang_out = ?",
                    (term.strip(), lang_in, lang_out)
                )
                if cursor.fetchone():
                    # 更新
                    conn.execute("""
                        UPDATE glossary
                        SET translation = ?, domain = ?, description = ?, case_sensitive = ?
                        WHERE term = ? AND lang_in = ? AND lang_out = ?
                    """, (translation.strip(), domain, description, int(case_sensitive),
                          term.strip(), lang_in, lang_out))
                else:
                    conn.execute("""
                        INSERT INTO glossary
                        (term, translation, lang_in, lang_out, domain, description, case_sensitive, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (term.strip(), translation.strip(), lang_in, lang_out,
                          domain, description, int(case_sensitive), time.time()))
            return True
        except Exception:
            return False

    def remove_term(self, term_id: int):
        """删除术语"""
        with safe_sqlite_connect(self.db_path) as conn:
            conn.execute("DELETE FROM glossary WHERE id = ?", (term_id,))

    def search_term(self, term: str, lang_in: str, lang_out: str) -> Optional[GlossaryEntry]:
        """查找术语"""
        with safe_sqlite_connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT * FROM glossary
                WHERE term = ? AND lang_in = ? AND lang_out = ?
            """, (term, lang_in, lang_out)).fetchone()

            if row:
                return GlossaryEntry(
                    id=row["id"],
                    term=row["term"],
                    translation=row["translation"],
                    lang_in=row["lang_in"],
                    lang_out=row["lang_out"],
                    domain=row["domain"],
                    description=row["description"],
                    case_sensitive=bool(row["case_sensitive"]),
                    created_at=row["created_at"],
                )
        return None

    def get_all_terms(self, lang_in: str = None, lang_out: str = None,
                      domain: str = None) -> list:
        """获取所有术语"""
        query = "SELECT * FROM glossary WHERE 1=1"
        params = []

        if lang_in:
            query += " AND lang_in = ?"
            params.append(lang_in)
        if lang_out:
            query += " AND lang_out = ?"
            params.append(lang_out)
        if domain:
            query += " AND domain = ?"
            params.append(domain)

        query += " ORDER BY term"

        with safe_sqlite_connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        return [
            GlossaryEntry(
                id=r["id"], term=r["term"], translation=r["translation"],
                lang_in=r["lang_in"], lang_out=r["lang_out"],
                domain=r["domain"], description=r["description"],
                case_sensitive=bool(r["case_sensitive"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def find_terms_in_text(self, text: str, lang_in: str, lang_out: str) -> list:
        """在文本中查找匹配的术语"""
        terms = self.get_all_terms(lang_in, lang_out)
        found = []

        for entry in terms:
            search_text = text if entry.case_sensitive else text.lower()
            search_term = entry.term if entry.case_sensitive else entry.term.lower()

            if search_term in search_text:
                found.append(entry)

        return found

    def import_glossary(self, filepath: str) -> int:
        """从文件导入术语库"""
        ext = Path(filepath).suffix.lower()

        if ext == "csv":
            return self._import_csv(filepath)
        elif ext == "json":
            return self._import_json(filepath)
        elif ext == "tbx":
            return self._import_tbx(filepath)
        return 0

    def _import_csv(self, filepath: str) -> int:
        """从 CSV 导入"""
        import csv
        count = 0
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if self.add_term(
                    term=row.get("Term", row.get("term", "")),
                    translation=row.get("Translation", row.get("translation", "")),
                    lang_in=row.get("LangIn", row.get("lang_in", "en")),
                    lang_out=row.get("LangOut", row.get("lang_out", "zh")),
                    domain=row.get("Domain", row.get("domain", "")),
                    description=row.get("Description", row.get("description", "")),
                ):
                    count += 1
        return count

    def _import_json(self, filepath: str) -> int:
        """从 JSON 导入"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        count = 0
        for item in data:
            if self.add_term(
                term=item.get("term", ""),
                translation=item.get("translation", ""),
                lang_in=item.get("lang_in", "en"),
                lang_out=item.get("lang_out", "zh"),
                domain=item.get("domain", ""),
                description=item.get("description", ""),
            ):
                count += 1
        return count

    def _import_tbx(self, filepath: str) -> int:
        """从 TBX (TermBase eXchange) 格式导入"""
        import xml.etree.ElementTree as ET
        count = 0
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()

            # 简单的 TBX 解析
            for term_entry in root.iter("termEntry"):
                lang_in = ""
                lang_out = ""
                term = ""
                translation = ""

                for lang_set in term_entry.iter("langSet"):
                    lang = lang_set.get("{http://www.w3.org/XML/1998/namespace}lang", "")
                    for tig in lang_set.iter("tig"):
                        for t_elem in tig.iter("term"):
                            if t_elem.text:
                                if not lang_in:
                                    lang_in = lang
                                    term = t_elem.text
                                else:
                                    lang_out = lang
                                    translation = t_elem.text

                if term and translation:
                    self.add_term(term, translation, lang_in or "en", lang_out or "zh")
                    count += 1
        except Exception:
            pass
        return count

    def export_glossary(self, filepath: str, format: str = "csv"):
        """导出术语库"""
        terms = self.get_all_terms()

        if format == "csv":
            import csv
            with open(filepath, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Term", "Translation", "LangIn", "LangOut", "Domain", "Description"])
                for t in terms:
                    writer.writerow([t.term, t.translation, t.lang_in, t.lang_out, t.domain, t.description])
        elif format == "json":
            data = [{"term": t.term, "translation": t.translation, "lang_in": t.lang_in,
                     "lang_out": t.lang_out, "domain": t.domain, "description": t.description}
                    for t in terms]
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def get_stats(self) -> dict:
        """获取术语库统计"""
        with safe_sqlite_connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM glossary").fetchone()[0]
            by_lang = conn.execute("""
                SELECT lang_in, lang_out, COUNT(*) as cnt
                FROM glossary GROUP BY lang_in, lang_out ORDER BY cnt DESC
            """).fetchall()
            by_domain = conn.execute("""
                SELECT domain, COUNT(*) as cnt
                FROM glossary WHERE domain != '' GROUP BY domain ORDER BY cnt DESC
            """).fetchall()

        return {
            "total_terms": total,
            "by_language": [(r[0], r[1], r[2]) for r in by_lang],
            "by_domain": [(r[0], r[1]) for r in by_domain],
        }