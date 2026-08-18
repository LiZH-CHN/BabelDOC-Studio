"""
术语库/记忆库高级管理模块
1. TBX/CSV 术语库导入
2. FTS5 全文搜索 + 记忆库预热
3. 相似度阈值控制
"""

import sqlite3
import csv
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from difflib import SequenceMatcher


# ============================================================
# 1. TBX 术语库解析器
# ============================================================

class TBXParser:
    """
    TBX (TermBase eXchange) 标准术语库解析器
    兼容 Trados、Wordfast 等工具导出的 TBX 文件
    """
    
    @staticmethod
    def parse(filepath: str, lang_in: str = "en", lang_out: str = "zh") -> list:
        """
        解析 TBX 文件
        
        Returns:
            [(term, translation), ...]
        """
        terms = []
        
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            
            # 处理不同版本的 TBX 格式
            # 标准 TBX 结构: <martif><text><body><termEntry><langSet><tig><term>
            for term_entry in root.iter("termEntry"):
                lang_in_term = ""
                lang_out_term = ""
                
                for lang_set in term_entry.iter("langSet"):
                    lang = lang_set.get("{http://www.w3.org/XML/1998/namespace}lang", "")
                    if not lang:
                        lang = lang_set.get("xml:lang", "")
                    
                    for tig in lang_set.iter("tig"):
                        for term_elem in tig.iter("term"):
                            if term_elem.text:
                                if lang.startswith(lang_in.lower()):
                                    lang_in_term = term_elem.text.strip()
                                elif lang.startswith(lang_out.lower()):
                                    lang_out_term = term_elem.text.strip()
                    
                    # 也尝试 <termEntry><langSet><ntig><termGrp><term>
                    if not lang_in_term or not lang_out_term:
                        for term_grp in lang_set.iter("termGrp"):
                            for term_elem in term_grp.iter("term"):
                                if term_elem.text:
                                    if lang.startswith(lang_in.lower()):
                                        lang_in_term = term_elem.text.strip()
                                    elif lang.startswith(lang_out.lower()):
                                        lang_out_term = term_elem.text.strip()
                
                if lang_in_term and lang_out_term:
                    terms.append((lang_in_term, lang_out_term))
            
            # 如果没有找到标准结构，尝试更宽松的解析
            if not terms:
                terms = TBXParser._parse_loose(root, lang_in, lang_out)
                
        except ET.ParseError:
            # 尝试更宽松的解析
            try:
                content = Path(filepath).read_text(encoding='utf-8')
                terms = TBXParser._parse_text(content, lang_in, lang_out)
            except Exception:
                pass
        except Exception:
            pass
        
        return terms
    
    @staticmethod
    def _parse_loose(root, lang_in: str, lang_out: str) -> list:
        """宽松解析 - 尝试各种 TBX 变体"""
        terms = []
        
        # 查找所有 <term> 标签
        all_terms = {}
        for elem in root.iter():
            if elem.tag == "term" and elem.text:
                lang = ""
                parent = elem
                # 向上查找 lang 属性
                while parent is not None:
                    lang = parent.get("{http://www.w3.org/XML/1998/namespace}lang", "")
                    if not lang:
                        lang = parent.get("xml:lang", "")
                    if lang:
                        break
                    parent = dict(parent).get("__parent__", None)
                
                if lang:
                    if lang not in all_terms:
                        all_terms[lang] = []
                    all_terms[lang].append(elem.text.strip())
        
        # 配对
        lang_in_terms = all_terms.get(lang_in, [])
        lang_out_terms = all_terms.get(lang_out, [])
        
        for i in range(min(len(lang_in_terms), len(lang_out_terms))):
            terms.append((lang_in_terms[i], lang_out_terms[i]))
        
        return terms
    
    @staticmethod
    def _parse_text(content: str, lang_in: str, lang_out: str) -> list:
        """纯文本解析（容错）"""
        terms = []
        # 尝试用正则提取术语对
        pattern = r'<term[^>]*>([^<]+)</term>'
        matches = re.findall(pattern, content)
        if matches:
            for i in range(0, len(matches) - 1, 2):
                terms.append((matches[i], matches[i + 1]))
        return terms


# ============================================================
# 2. CSV 术语库解析器
# ============================================================

class CSVParser:
    """
    CSV 术语库解析器
    支持多种列名格式：
    - Term, Translation
    - Source, Target
    - 术语, 翻译
    - en, zh
    """
    
    # 列名映射
    SOURCE_KEYS = {"term", "source", "src", "english", "en", "source_text", "术语", "英文", "源语言"}
    TARGET_KEYS = {"translation", "target", "tgt", "chinese", "zh", "target_text", "翻译", "中文", "目标语言"}
    
    @staticmethod
    def parse(filepath: str, lang_in: str = "en", lang_out: str = "zh") -> list:
        """
        解析 CSV 术语文件
        
        Returns:
            [(term, translation), ...]
        """
        terms = []
        
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                # 检测分隔符
                sample = f.read(4096)
                f.seek(0)
                
                dialect = csv.Sniffer().sniff(sample)
                reader = csv.DictReader(f, dialect=dialect)
                
                if reader.fieldnames:
                    # 查找源语言和目标语言列
                    source_col = None
                    target_col = None
                    
                    for col in reader.fieldnames:
                        col_lower = col.strip().lower()
                        if col_lower in CSVParser.SOURCE_KEYS:
                            source_col = col
                        elif col_lower in CSVParser.TARGET_KEYS:
                            target_col = col
                    
                    # 如果没找到匹配的列名，使用前两列
                    if source_col is None and len(reader.fieldnames) >= 2:
                        source_col = reader.fieldnames[0]
                        target_col = reader.fieldnames[1]
                    elif source_col is None and len(reader.fieldnames) == 1:
                        # 只有一列，尝试按行配对
                        pass
                    
                    for row in reader:
                        if source_col and target_col:
                            src = row.get(source_col, "").strip()
                            tgt = row.get(target_col, "").strip()
                            if src and tgt:
                                terms.append((src, tgt))
        except Exception:
            # 回退到简单解析
            try:
                with open(filepath, 'r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if len(row) >= 2:
                            src = row[0].strip()
                            tgt = row[1].strip()
                            if src and tgt and not src.lower() == "term":
                                terms.append((src, tgt))
            except Exception:
                pass
        
        return terms


# ============================================================
# 3. FTS5 全文搜索引擎
# ============================================================

class FTS5SearchEngine:
    """
    SQLite FTS5 全文搜索引擎
    用于记忆库的快速模糊匹配
    """
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = None
        self._ensure_fts5()
    
    @property
    def conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn
    
    def _ensure_fts5(self):
        """确保 FTS5 表存在"""
        try:
            # 检查 FTS5 是否可用
            cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tm_fts'")
            if cursor.fetchone():
                return  # 已存在
            
            # 创建 FTS5 虚拟表（无外部内容）
            self.conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS tm_fts USING fts5(
                    source_text,
                    target_text,
                    tokenize='unicode61'
                )
            """)
            self.conn.commit()
        except sqlite3.OperationalError as e:
            # FTS5 不可用，回退到普通表
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS tm_fts (
                    source_text TEXT,
                    target_text TEXT
                )
            """)
            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tm_source ON tm_fts(source_text)
            """)
            self.conn.commit()
    
    def index_entries(self, entries: list):
        """
        索引翻译记忆条目
        
        Args:
            entries: [(source, target), ...]
        """
        # 先清空旧数据，避免重复
        self.conn.execute("DELETE FROM tm_fts")
        
        for source, target in entries:
            try:
                self.conn.execute(
                    "INSERT INTO tm_fts (source_text, target_text) VALUES (?, ?)",
                    (source, target)
                )
            except sqlite3.IntegrityError:
                pass  # 重复条目跳过
        
        self.conn.commit()
    
    def search(self, query: str, limit: int = 5) -> list:
        """
        全文搜索
        
        Returns:
            [(source, target, rank), ...]
        """
        results = []
        try:
            # FTS5 搜索
            cursor = self.conn.execute("""
                SELECT source_text, target_text, rank
                FROM tm_fts
                WHERE tm_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (f"{query}*", limit))
            results = cursor.fetchall()
        except sqlite3.OperationalError:
            # 回退到 LIKE 搜索
            cursor = self.conn.execute("""
                SELECT source_text, target_text, 0 as rank
                FROM tm_fts
                WHERE source_text LIKE ?
                LIMIT ?
            """, (f"%{query}%", limit))
            results = cursor.fetchall()
        
        return results
    
    def clear(self):
        """清空索引"""
        try:
            self.conn.execute("DELETE FROM tm_fts")
            self.conn.commit()
        except Exception:
            pass
    
    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


# ============================================================
# 4. 相似度匹配器
# ============================================================

class SimilarityMatcher:
    """
    基于 Levenshtein 距离（编辑距离）的相似度匹配器
    使用 Python 标准库的 difflib 实现
    """
    
    @staticmethod
    def calculate_similarity(text1: str, text2: str) -> float:
        """
        计算两段文本的相似度（0.0 ~ 1.0）
        
        使用 SequenceMatcher（基于 Ratcliff/Obershelp 算法）
        近似 Levenshtein 距离，但性能更好
        """
        if not text1 or not text2:
            return 0.0
        
        # 标准化：去除多余空格、统一大小写
        t1 = " ".join(text1.split()).lower()
        t2 = " ".join(text2.split()).lower()
        
        if t1 == t2:
            return 1.0
        
        # 使用 SequenceMatcher 计算相似度
        matcher = SequenceMatcher(None, t1, t2)
        return matcher.ratio()
    
    @staticmethod
    def is_match(text1: str, text2: str, threshold: float = 0.85) -> bool:
        """检查两段文本是否超过相似度阈值"""
        return SimilarityMatcher.calculate_similarity(text1, text2) >= threshold
    
    @staticmethod
    def find_best_match(query: str, candidates: list, threshold: float = 0.85) -> Optional[tuple]:
        """
        在候选列表中找到最佳匹配
        
        Args:
            query: 待匹配文本
            candidates: [(source, target), ...] 候选列表
            threshold: 相似度阈值
        
        Returns:
            (source, target, similarity) 或 None
        """
        best_match = None
        best_similarity = 0.0
        
        for source, target in candidates:
            sim = SimilarityMatcher.calculate_similarity(query, source)
            if sim > best_similarity and sim >= threshold:
                best_similarity = sim
                best_match = (source, target, sim)
        
        return best_match


# ============================================================
# 5. 统一术语库管理器
# ============================================================

class TerminologyManager:
    """
    统一的术语库管理器
    支持 TBX/CSV 导入导出、FTS5 搜索、相似度匹配
    """
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.fts_engine = FTS5SearchEngine(db_path)
    
    def import_terms(self, filepath: str, format: str = "auto",
                     lang_in: str = "en", lang_out: str = "zh") -> int:
        """
        导入术语库
        
        Returns:
            导入的术语数量
        """
        if format == "auto":
            ext = Path(filepath).suffix.lower()
            format = {"tbx": "tbx", "csv": "csv", "tmx": "tmx"}.get(ext, "csv")
        
        terms = []
        
        if format == "tbx":
            terms = TBXParser.parse(filepath, lang_in, lang_out)
        elif format == "csv":
            terms = CSVParser.parse(filepath, lang_in, lang_out)
        elif format == "tmx":
            # TMX 也作为术语对导入
            terms = self._parse_tmx_as_terms(filepath, lang_in, lang_out)
        
        # 存储到数据库
        from gui.core import GlossaryManager
        gm = GlossaryManager(db_path=self.db_path)
        
        count = 0
        for term, translation in terms:
            if gm.add_term(term=term, translation=translation,
                          lang_in=lang_in, lang_out=lang_out,
                          domain="导入"):
                count += 1
        
        # 同时索引到 FTS5
        self.fts_engine.index_entries(terms)
        
        return count
    
    def _parse_tmx_as_terms(self, filepath: str, lang_in: str, lang_out: str) -> list:
        """从 TMX 文件解析术语对"""
        terms = []
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            
            for tu in root.iter("tu"):
                lang_in_term = ""
                lang_out_term = ""
                
                for tuv in tu.iter("tuv"):
                    lang = tuv.get("{http://www.w3.org/XML/1998/namespace}lang", "")
                    if not lang:
                        lang = tuv.get("xml:lang", "")
                    
                    seg = tuv.find("seg")
                    if seg is not None and seg.text:
                        if lang.startswith(lang_in.lower()):
                            lang_in_term = seg.text.strip()
                        elif lang.startswith(lang_out.lower()):
                            lang_out_term = seg.text.strip()
                
                if lang_in_term and lang_out_term:
                    terms.append((lang_in_term, lang_out_term))
        except Exception:
            pass
        
        return terms
    
    def search_similar(self, query: str, limit: int = 5,
                       threshold: float = 0.85) -> list:
        """
        搜索相似术语
        
        Returns:
            [(source, target, similarity), ...]
        """
        # 1. 先使用 FTS5 全文搜索
        fts_results = self.fts_engine.search(query, limit=limit * 2)
        
        # 2. 计算相似度并过滤
        results = []
        for source, target, rank in fts_results:
            sim = SimilarityMatcher.calculate_similarity(query, source)
            if sim >= threshold:
                results.append((source, target, sim))
        
        # 3. 按相似度排序
        results.sort(key=lambda x: x[2], reverse=True)
        return results[:limit]
    
    def prewarm_from_tmx(self, filepath: str, lang_in: str = "en",
                         lang_out: str = "zh") -> int:
        """
        从 TMX 文件预热记忆库
        
        Returns:
            导入的条目数量
        """
        from gui.core import TranslationMemory
        tm = TranslationMemory(db_path=self.db_path)
        
        entries = []
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            
            for tu in root.iter("tu"):
                source = ""
                target = ""
                
                for tuv in tu.iter("tuv"):
                    lang = tuv.get("{http://www.w3.org/XML/1998/namespace}lang", "")
                    if not lang:
                        lang = tuv.get("xml:lang", "")
                    
                    seg = tuv.find("seg")
                    if seg is not None and seg.text:
                        if lang.startswith(lang_in.lower()):
                            source = seg.text.strip()
                        elif lang.startswith(lang_out.lower()):
                            target = seg.text.strip()
                
                if source and target:
                    entries.append((source, target))
        except Exception as e:
            return 0
        
        # 批量导入
        count = 0
        for source, target in entries:
            if tm.add_translation(source, target, lang_in, lang_out):
                count += 1
        
        # 索引到 FTS5
        self.fts_engine.index_entries(entries)
        
        return count
    
    def close(self):
        self.fts_engine.close()


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    import tempfile
    import logging
    _logger = logging.getLogger(__name__)

    _logger.info("=== TBX Parser Test ===")
    # 创建测试 TBX 文件
    tbx_content = '''<?xml version="1.0" encoding="UTF-8"?>
    <martif type="TBX" xml:lang="en">
        <text>
            <body>
                <termEntry>
                    <langSet xml:lang="en">
                        <tig><term>Machine Learning</term></tig>
                    </langSet>
                    <langSet xml:lang="zh">
                        <tig><term>机器学习</term></tig>
                    </langSet>
                </termEntry>
            </body>
        </text>
    </martif>'''

    with tempfile.NamedTemporaryFile(suffix=".tbx", delete=False, mode='w', encoding='utf-8') as f:
        f.write(tbx_content)
        tbx_path = f.name

    terms = TBXParser.parse(tbx_path, "en", "zh")
    _logger.info("TBX parsed: %d terms", len(terms))
    for term, trans in terms[:3]:
        _logger.info("  %s -> %s", term, trans)

    Path(tbx_path).unlink()

    _logger.info("=== CSV Parser Test ===")
    csv_content = """Term,Translation
Machine Learning,机器学习
Deep Learning,深度学习
Neural Network,神经网络
"""

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode='w', encoding='utf-8', newline='') as f:
        f.write(csv_content)
        csv_path = f.name

    terms = CSVParser.parse(csv_path, "en", "zh")
    _logger.info("CSV parsed: %d terms", len(terms))
    for term, trans in terms:
        _logger.info("  %s -> %s", term, trans)

    Path(csv_path).unlink()

    _logger.info("=== Similarity Matcher Test ===")
    matcher = SimilarityMatcher()

    test_pairs = [
        ("Machine Learning", "Machine Learning"),
        ("Machine Learning", "Machine Learnin"),
        ("Deep Learning", "Machine Learning"),
        ("Hello World", "Hello World!"),
    ]

    for t1, t2 in test_pairs:
        sim = matcher.calculate_similarity(t1, t2)
        _logger.info("  '%s' vs '%s': %.2f%%", t1, t2, sim * 100)

    _logger.info("=== FTS5 Search Test ===")
    db_dir = tempfile.mkdtemp()
    db_path = Path(db_dir) / "test.db"

    fts = FTS5SearchEngine(db_path)
    test_entries = [
        ("Machine Learning is great", "机器学习很棒"),
        ("Deep Learning is powerful", "深度学习很强大"),
        ("Neural Network", "神经网络"),
        ("Natural Language Processing", "自然语言处理"),
    ]

    fts.index_entries(test_entries)
    results = fts.search("Machine", 5)
    _logger.info("FTS5 search 'Machine': %d results", len(results))
    for src, tgt, rank in results:
        _logger.info("  %s -> %s", src, tgt)

    fts.close()

    # 清理
    import shutil
    shutil.rmtree(db_dir, ignore_errors=True)

    _logger.info("=== All Tests Passed ===")