"""
翻译质量与记忆模块
包含：翻译记忆库、术语库、QA 检查、质量评分、术语替换、高级翻译功能
"""

import sqlite3
import json
import hashlib
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict


# ============================================================
# 探针 6 加固：SQLite 安全连接工厂
# 多引擎并发写入 tm_cache.db / cost_analysis.db 时，
# 裸 sqlite3.connect 会触发 "database is locked"。
# 统一启用 WAL 预写日志 + 30s busy_timeout。
# ============================================================

def safe_sqlite_connect(db_path, timeout: float = 30.0):
    """创建带 WAL 和 busy_timeout 的 SQLite 连接。

    Args:
        db_path: 数据库路径
        timeout: busy_timeout（秒），默认 30s

    Returns:
        sqlite3.Connection 已配置 WAL 的连接
    """
    conn = sqlite3.connect(db_path, timeout=timeout)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
        # 正常同步级别，兼顾安全与性能
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    return conn


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
                CREATE INDEX IF NOT EXISTS idx_glossary_domain ON glossary(domain);

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

    def search_similar(self, text: str, lang_in: str, lang_out: str,
                       threshold: float = 0.8, limit: int = 5) -> list:
        """搜索相似翻译（基于简单相似度）"""
        results = []
        text_lower = text.lower().strip()

        with safe_sqlite_connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM translation_memory
                WHERE lang_in = ? AND lang_out = ?
                ORDER BY score DESC, used_count DESC
            """, (lang_in, lang_out)).fetchall()

            for row in rows:
                similarity = self._calculate_similarity(text_lower, row["source_text"].lower())
                if similarity >= threshold:
                    entry = TMEntry(
                        id=row["id"],
                        source_text=row["source_text"],
                        target_text=row["target_text"],
                        lang_in=row["lang_in"],
                        lang_out=row["lang_out"],
                        project=row["project"],
                        domain=row["domain"],
                        created_at=row["created_at"],
                        used_count=row["used_count"],
                        last_used=row["last_used"],
                        score=row["score"],
                    )
                    results.append((entry, similarity))

        # 按相似度排序
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

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

    @staticmethod
    def _calculate_similarity(text1: str, text2: str) -> float:
        """计算两个文本的相似度（基于 Levenshtein 距离）"""
        if text1 == text2:
            return 1.0

        len1, len2 = len(text1), len(text2)
        if len1 == 0 or len2 == 0:
            return 0.0

        # 简单的基于词的相似度
        words1 = set(text1.split())
        words2 = set(text2.split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        jaccard = len(intersection) / len(union) if union else 0

        # 结合字符级相似度
        # 使用简单的最长公共子序列近似
        common = sum(1 for c in text1 if c in text2)
        char_sim = 2 * common / (len1 + len2) if (len1 + len2) > 0 else 0

        return 0.6 * jaccard + 0.4 * char_sim

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


# 导入术语替换和 AI 术语库模块
from .term_replacer import TermReplacer, TermInjector, SmartTermMatcher, create_default_replacer
from .ai_glossary import AI_CS_GLOSSARY, get_all_terms, get_terms_by_domain, get_domains, get_sub_domains
from .domain_detector import detect_domain, get_best_domain, get_all_domains

# 导入高级翻译功能模块
from .advanced_translation import (
    CostAnalyzer, CostRecord, CostSummary,
    MultiEngineTranslator, TranslationCandidate,
    AdaptiveMT, FeedbackEntry,
    ImageTranslator, OCRResult,
    MODEL_PRICING, DEFAULT_PRICING,
)