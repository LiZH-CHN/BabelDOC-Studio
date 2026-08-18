"""
翻译记忆库模块
包含：TranslationMemory 类、TMEntry 数据类
提供翻译记忆库的增删改查、导入导出功能
"""

import sqlite3
import json
import hashlib
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from gui.core.sqlite_utils import safe_sqlite_connect


@dataclass
class TMEntry:
    """翻译记忆条目"""
    id: int = 0
    source_text: str = ""
    target_text: str = ""
    lang_in: str = ""
    lang_out: str = ""
    project: str = ""
    domain: str = ""
    created_at: float = 0.0
    used_count: int = 0
    last_used: float = 0.0
    score: float = 1.0  # 匹配质量评分


class TranslationMemory:
    """翻译记忆库管理器"""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "data" / "translation_memory.db"
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        with safe_sqlite_connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS translation_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_text TEXT NOT NULL,
                    target_text TEXT NOT NULL,
                    lang_in TEXT NOT NULL,
                    lang_out TEXT NOT NULL,
                    project TEXT DEFAULT '',
                    domain TEXT DEFAULT '',
                    created_at REAL DEFAULT 0,
                    used_count INTEGER DEFAULT 0,
                    last_used REAL DEFAULT 0,
                    score REAL DEFAULT 1.0,
                    text_hash TEXT UNIQUE
                );

                CREATE INDEX IF NOT EXISTS idx_tm_hash ON translation_memory(text_hash);
                CREATE INDEX IF NOT EXISTS idx_tm_lang ON translation_memory(lang_in, lang_out);
                CREATE INDEX IF NOT EXISTS idx_tm_project ON translation_memory(project);
                CREATE INDEX IF NOT EXISTS idx_tm_domain ON translation_memory(domain);

                CREATE TABLE IF NOT EXISTS qa_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    rule_type TEXT NOT NULL,
                    config TEXT DEFAULT '{}',
                    enabled INTEGER DEFAULT 1,
                    created_at REAL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS translation_projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    lang_in TEXT DEFAULT '',
                    lang_out TEXT DEFAULT '',
                    domain TEXT DEFAULT '',
                    created_at REAL DEFAULT 0,
                    updated_at REAL DEFAULT 0
                );
            """)

    @staticmethod
    def _hash_text(text: str) -> str:
        """计算文本哈希（用于快速查重）"""
        normalized = " ".join(text.split()).lower()
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()

    # ============================================================
    # 翻译记忆操作
    # ============================================================

    def add_translation(self, source: str, target: str, lang_in: str, lang_out: str,
                        project: str = "", domain: str = "", score: float = 1.0) -> bool:
        """添加翻译到记忆库"""
        if not source.strip() or not target.strip():
            return False

        text_hash = self._hash_text(source)
        now = time.time()

        try:
            with safe_sqlite_connect(self.db_path) as conn:
                # 检查是否已存在
                cursor = conn.execute(
                    "SELECT id FROM translation_memory WHERE text_hash = ? AND lang_in = ? AND lang_out = ?",
                    (text_hash, lang_in, lang_out)
                )
                existing = cursor.fetchone()

                if existing:
                    # 更新已有条目
                    conn.execute("""
                        UPDATE translation_memory
                        SET target_text = ?, score = ?, used_count = used_count + 1, last_used = ?
                        WHERE id = ?
                    """, (target, score, now, existing[0]))
                else:
                    # 插入新条目
                    conn.execute("""
                        INSERT INTO translation_memory
                        (source_text, target_text, lang_in, lang_out, project, domain,
                         created_at, used_count, last_used, score, text_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """, (source.strip(), target.strip(), lang_in, lang_out,
                          project, domain, now, now, score, text_hash))
            return True
        except Exception:
            return False

    def get_exact_match(self, text: str, lang_in: str, lang_out: str) -> Optional[TMEntry]:
        """精确匹配"""
        text_hash = self._hash_text(text)

        with safe_sqlite_connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT * FROM translation_memory
                WHERE text_hash = ? AND lang_in = ? AND lang_out = ?
            """, (text_hash, lang_in, lang_out)).fetchone()

            if row:
                # 更新使用统计
                conn.execute("""
                    UPDATE translation_memory
                    SET used_count = used_count + 1, last_used = ?
                    WHERE id = ?
                """, (time.time(), row["id"]))

                return TMEntry(
                    id=row["id"],
                    source_text=row["source_text"],
                    target_text=row["target_text"],
                    lang_in=row["lang_in"],
                    lang_out=row["lang_out"],
                    project=row["project"],
                    domain=row["domain"],
                    score=row["score"],
                )
        return None

    def get_stats(self) -> dict:
        """获取记忆库统计信息"""
        with safe_sqlite_connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM translation_memory").fetchone()[0]
            by_lang = conn.execute("""
                SELECT lang_in, lang_out, COUNT(*) as cnt
                FROM translation_memory
                GROUP BY lang_in, lang_out
                ORDER BY cnt DESC
            """).fetchall()
            by_domain = conn.execute("""
                SELECT domain, COUNT(*) as cnt
                FROM translation_memory
                WHERE domain != ''
                GROUP BY domain
                ORDER BY cnt DESC
            """).fetchall()
            total_used = conn.execute(
                "SELECT SUM(used_count) FROM translation_memory"
            ).fetchone()[0]

        return {
            "total_entries": total,
            "total_usage": total_used or 0,
            "by_language": [(r[0], r[1], r[2]) for r in by_lang],
            "by_domain": [(r[0], r[1]) for r in by_domain],
        }

    def export_tm(self, filepath: str, format: str = "tmx"):
        """导出翻译记忆"""
        with safe_sqlite_connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM translation_memory").fetchall()

        if format == "tmx":
            self._export_tmx(filepath, rows)
        elif format == "csv":
            self._export_csv(filepath, rows)
        elif format == "json":
            self._export_json(filepath, rows)

    def _export_tmx(self, filepath: str, rows):
        """导出为 TMX 格式"""
        header = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE tmx SYSTEM "tmx14.dtd">
<tmx version="1.4">
<header creationtool="BabelDOC-GUI" srclang="*all*"/>
<body>
"""
        footer = "</body>\n</xml>"

        tus = []
        for row in rows:
            src = row["source_text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            tgt = row["target_text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            tu = f"""  <tu>
    <tuv xml:lang=\"{row['lang_in']}\"><seg>{src}</seg></tuv>
    <tuv xml:lang=\"{row['lang_out']}\"><seg>{tgt}</seg></tuv>
  </tu>"""
            tus.append(tu)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(tus) + "\n" + footer)

    def _export_csv(self, filepath: str, rows):
        """导出为 CSV 格式"""
        import csv
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Source", "Target", "LangIn", "LangOut", "Domain", "Score"])
            for row in rows:
                writer.writerow([
                    row["source_text"], row["target_text"],
                    row["lang_in"], row["lang_out"],
                    row["domain"], row["score"]
                ])

    def _export_json(self, filepath: str, rows):
        """导出为 JSON 格式"""
        data = []
        for row in rows:
            data.append({
                "source": row["source_text"],
                "target": row["target_text"],
                "lang_in": row["lang_in"],
                "lang_out": row["lang_out"],
                "domain": row["domain"],
                "score": row["score"],
            })
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def import_tm(self, filepath: str, format: str = "auto") -> int:
        """导入翻译记忆"""
        if format == "auto":
            ext = Path(filepath).suffix.lower()
            format = {"tmx": "tmx", "csv": "csv", "json": "json"}.get(ext, "json")

        if format == "json":
            return self._import_json(filepath)
        elif format == "csv":
            return self._import_csv(filepath)
        return 0

    def _import_json(self, filepath: str) -> int:
        """从 JSON 导入"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        count = 0
        for item in data:
            if self.add_translation(
                source=item.get("source", ""),
                target=item.get("target", ""),
                lang_in=item.get("lang_in", "en"),
                lang_out=item.get("lang_out", "zh"),
                domain=item.get("domain", ""),
                score=item.get("score", 1.0),
            ):
                count += 1
        return count

    def _import_csv(self, filepath: str) -> int:
        """从 CSV 导入"""
        import csv
        count = 0
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if self.add_translation(
                    source=row.get("Source", ""),
                    target=row.get("Target", ""),
                    lang_in=row.get("LangIn", "en"),
                    lang_out=row.get("LangOut", "zh"),
                    domain=row.get("Domain", ""),
                ):
                    count += 1
        return count

    def clear(self, lang_in: str = None, lang_out: str = None):
        """清除记忆库"""
        with safe_sqlite_connect(self.db_path) as conn:
            if lang_in and lang_out:
                conn.execute(
                    "DELETE FROM translation_memory WHERE lang_in = ? AND lang_out = ?",
                    (lang_in, lang_out)
                )
            else:
                conn.execute("DELETE FROM translation_memory")