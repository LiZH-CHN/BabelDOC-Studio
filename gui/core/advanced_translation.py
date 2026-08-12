"""
高级翻译功能模块
包含：翻译成本分析、多引擎对比、自适应MT、图片/OCR翻译
"""

import json
import time
import sqlite3
import hashlib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict


# 探针 6 加固：SQLite 安全连接工厂（WAL + 30s busy_timeout）
def _safe_sqlite_connect(db_path, timeout: float = 30.0):
    """创建带 WAL 和 busy_timeout 的 SQLite 连接，防止多引擎并发锁死。"""
    conn = sqlite3.connect(db_path, timeout=timeout)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    return conn


# ============================================================
# 1. 翻译成本分析
# ============================================================

# 模型价格表（每 1K Token 价格，单位：人民币）
MODEL_PRICING = {
    # DeepSeek
    "deepseek-chat": {"input": 0.001, "output": 0.002, "cached_input": 0.0001},
    "deepseek-reasoner": {"input": 0.002, "output": 0.004, "cached_input": 0.0002},
    "deepseek-v4-flash": {"input": 0.0005, "output": 0.001, "cached_input": 0.00005},
    "deepseek-v4-pro": {"input": 0.002, "output": 0.004, "cached_input": 0.0002},
    # GLM
    "glm-4": {"input": 0.014, "output": 0.014, "cached_input": 0.0014},
    "glm-4-plus": {"input": 0.05, "output": 0.05, "cached_input": 0.005},
    "glm-4-air": {"input": 0.001, "output": 0.001, "cached_input": 0.0001},
    "glm-4-flash": {"input": 0.0001, "output": 0.0001, "cached_input": 0.00001},
    "glm-4.5": {"input": 0.02, "output": 0.02, "cached_input": 0.002},
    "glm-4.5-air": {"input": 0.005, "output": 0.005, "cached_input": 0.0005},
    "glm-4.5-airx": {"input": 0.003, "output": 0.003, "cached_input": 0.0003},
    "glm-4.5-flash": {"input": 0.0001, "output": 0.0001, "cached_input": 0.00001},
    "glm-4.6": {"input": 0.01, "output": 0.01, "cached_input": 0.001},
    "glm-4.6v": {"input": 0.01, "output": 0.01, "cached_input": 0.001},
    "glm-4.7": {"input": 0.015, "output": 0.015, "cached_input": 0.0015},
    "glm-4.7-flash": {"input": 0.0001, "output": 0.0001, "cached_input": 0.00001},
    "glm-4.7-flashx": {"input": 0.001, "output": 0.001, "cached_input": 0.0001},
    "glm-4-long": {"input": 0.001, "output": 0.001, "cached_input": 0.0001},
    "glm-4-flashx-250414": {"input": 0.0001, "output": 0.0001, "cached_input": 0.00001},
    "glm-5": {"input": 0.05, "output": 0.05, "cached_input": 0.005},
    "glm-5.1": {"input": 0.08, "output": 0.08, "cached_input": 0.008},
    "glm-5.2": {"input": 0.1, "output": 0.1, "cached_input": 0.01},
    "glm-5-turbo": {"input": 0.06, "output": 0.06, "cached_input": 0.006},
    "glm-5v-turbo": {"input": 0.06, "output": 0.06, "cached_input": 0.006},
    # Kimi
    "moonshot-v1-8k": {"input": 0.012, "output": 0.012, "cached_input": 0.0012},
    "moonshot-v1-32k": {"input": 0.024, "output": 0.024, "cached_input": 0.0024},
    "moonshot-v1-128k": {"input": 0.06, "output": 0.06, "cached_input": 0.006},
    "moonshot-v1-auto": {"input": 0.024, "output": 0.024, "cached_input": 0.0024},
    "kimi-k2.5": {"input": 0.012, "output": 0.012, "cached_input": 0.0012},
    "kimi-k2.6": {"input": 0.015, "output": 0.015, "cached_input": 0.0015},
    "kimi-k2.7-code": {"input": 0.02, "output": 0.02, "cached_input": 0.002},
    "kimi-k2.7-code-highspeed": {"input": 0.025, "output": 0.025, "cached_input": 0.0025},
    "kimi-k3": {"input": 0.03, "output": 0.03, "cached_input": 0.003},
    # OpenAI
    "gpt-5.6-sol": {"input": 0.15, "output": 0.6, "cached_input": 0.075},
    "gpt-5.6-terra": {"input": 0.05, "output": 0.2, "cached_input": 0.025},
    "gpt-5.6-luna": {"input": 0.01, "output": 0.04, "cached_input": 0.005},
    "gpt-5": {"input": 0.05, "output": 0.2, "cached_input": 0.025},
    "gpt-5-mini": {"input": 0.005, "output": 0.02, "cached_input": 0.0025},
    "gpt-4.1": {"input": 0.01, "output": 0.04, "cached_input": 0.005},
    "gpt-4.1-mini": {"input": 0.001, "output": 0.004, "cached_input": 0.0005},
    "o3": {"input": 0.05, "output": 0.2, "cached_input": 0.025},
    "o4-mini": {"input": 0.005, "output": 0.02, "cached_input": 0.0025},
    "gpt-4o": {"input": 0.018, "output": 0.072, "cached_input": 0.009},
    "gpt-4o-mini": {"input": 0.0011, "output": 0.0045, "cached_input": 0.00055},
    "gpt-4-turbo": {"input": 0.072, "output": 0.216, "cached_input": 0.036},
    "gpt-3.5-turbo": {"input": 0.0036, "output": 0.0072, "cached_input": 0.0018},
    "o1-preview": {"input": 0.108, "output": 0.432, "cached_input": 0.054},
    "o1-mini": {"input": 0.022, "output": 0.086, "cached_input": 0.011},
    # Qwen
    "qwen-max": {"input": 0.014, "output": 0.042, "cached_input": 0.0014},
    "qwen-plus": {"input": 0.006, "output": 0.018, "cached_input": 0.0006},
    "qwen-turbo": {"input": 0.002, "output": 0.006, "cached_input": 0.0002},
    "qwen-long": {"input": 0.001, "output": 0.002, "cached_input": 0.0001},
    "qwen3.8-max-preview": {"input": 0.03, "output": 0.09, "cached_input": 0.003},
    "qwen3.7-max": {"input": 0.04, "output": 0.16, "cached_input": 0.004},
    "qwen3.7-plus": {"input": 0.008, "output": 0.032, "cached_input": 0.0008},
    "qwen3.7-flash": {"input": 0.001, "output": 0.004, "cached_input": 0.0001},

    # LongCat
    "LongCat-2.0": {"input": 0.001, "output": 0.002, "cached_input": 0.0001},
}

# 默认价格（未知模型）
DEFAULT_PRICING = {"input": 0.01, "output": 0.02, "cached_input": 0.001}


@dataclass
class CostRecord:
    """成本记录"""
    id: int = 0
    project: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    timestamp: float = 0.0
    file_name: str = ""


@dataclass
class CostSummary:
    """成本汇总"""
    total_cost: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_cached_tokens: int = 0
    by_model: dict = field(default_factory=dict)
    by_project: dict = field(default_factory=dict)
    by_date: dict = field(default_factory=dict)
    record_count: int = 0


class CostAnalyzer:
    """翻译成本分析器"""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "data" / "cost_analysis.db"
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        with _safe_sqlite_connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS cost_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project TEXT DEFAULT '',
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    cached_tokens INTEGER DEFAULT 0,
                    input_cost REAL DEFAULT 0,
                    output_cost REAL DEFAULT 0,
                    total_cost REAL DEFAULT 0,
                    timestamp REAL DEFAULT 0,
                    file_name TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_cost_project ON cost_records(project);
                CREATE INDEX IF NOT EXISTS idx_cost_model ON cost_records(model);
                CREATE INDEX IF NOT EXISTS idx_cost_timestamp ON cost_records(timestamp);
            """)

    @staticmethod
    def get_model_pricing(model: str) -> dict:
        """获取模型价格"""
        return MODEL_PRICING.get(model, DEFAULT_PRICING)

    @staticmethod
    def calculate_cost(prompt_tokens: int, completion_tokens: int,
                       cached_tokens: int, model: str) -> dict:
        """
        计算翻译成本

        Returns:
            dict with input_cost, output_cost, total_cost
        """
        # 探针 8 加固：空文档 usage 为空时 None 防御，防止 float(None) 崩溃
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        cached_tokens = max(0, int(cached_tokens or 0))

        pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)

        # 非缓存 input tokens
        non_cached_input = max(0, prompt_tokens - cached_tokens)

        input_cost = (non_cached_input / 1000) * pricing["input"]
        cached_cost = (cached_tokens / 1000) * pricing.get("cached_input", pricing["input"] * 0.1)
        output_cost = (completion_tokens / 1000) * pricing["output"]

        return {
            "input_cost": input_cost + cached_cost,
            "output_cost": output_cost,
            "total_cost": input_cost + cached_cost + output_cost,
        }

    def record_translation(self, model: str, prompt_tokens: int,
                           completion_tokens: int, cached_tokens: int = 0,
                           project: str = "", file_name: str = "") -> CostRecord:
        """记录翻译成本"""
        costs = self.calculate_cost(prompt_tokens, completion_tokens, cached_tokens, model)
        now = time.time()

        record = CostRecord(
            project=project,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cached_tokens=cached_tokens,
            input_cost=costs["input_cost"],
            output_cost=costs["output_cost"],
            total_cost=costs["total_cost"],
            timestamp=now,
            file_name=file_name,
        )

        with _safe_sqlite_connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO cost_records
                (project, model, prompt_tokens, completion_tokens, total_tokens,
                 cached_tokens, input_cost, output_cost, total_cost, timestamp, file_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (record.project, record.model, record.prompt_tokens,
                  record.completion_tokens, record.total_tokens, record.cached_tokens,
                  record.input_cost, record.output_cost, record.total_cost,
                  record.timestamp, record.file_name))

        return record

    def get_summary(self, project: str = None, start_time: float = None,
                    end_time: float = None) -> CostSummary:
        """获取成本汇总"""
        query = "SELECT * FROM cost_records WHERE 1=1"
        params = []

        if project:
            query += " AND project = ?"
            params.append(project)
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)

        with _safe_sqlite_connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        summary = CostSummary()
        by_model = defaultdict(lambda: {"cost": 0, "tokens": 0, "count": 0})
        by_project = defaultdict(lambda: {"cost": 0, "tokens": 0, "count": 0})
        by_date = defaultdict(lambda: {"cost": 0, "tokens": 0, "count": 0})

        for row in rows:
            summary.total_cost += row["total_cost"]
            summary.total_prompt_tokens += row["prompt_tokens"]
            summary.total_completion_tokens += row["completion_tokens"]
            summary.total_tokens += row["total_tokens"]
            summary.total_cached_tokens += row["cached_tokens"]
            summary.record_count += 1

            model = row["model"]
            by_model[model]["cost"] += row["total_cost"]
            by_model[model]["tokens"] += row["total_tokens"]
            by_model[model]["count"] += 1

            proj = row["project"] or "未分类"
            by_project[proj]["cost"] += row["total_cost"]
            by_project[proj]["tokens"] += row["total_tokens"]
            by_project[proj]["count"] += 1

            date_str = time.strftime("%Y-%m-%d", time.localtime(row["timestamp"]))
            by_date[date_str]["cost"] += row["total_cost"]
            by_date[date_str]["tokens"] += row["total_tokens"]
            by_date[date_str]["count"] += 1

        summary.by_model = dict(by_model)
        summary.by_project = dict(by_project)
        summary.by_date = dict(sorted(by_date.items()))

        return summary

    def estimate_cost(self, total_chars: int, model: str,
                      lang_in: str = "en", lang_out: str = "zh") -> dict:
        """
        预估翻译成本

        Args:
            total_chars: 总字符数
            model: 模型名称
            lang_in: 源语言
            lang_out: 目标语言

        Returns:
            预估结果
        """
        # 估算 token 数
        if lang_in == "en":
            prompt_tokens = int(total_chars / 4)  # 英文约 4 字符/token
        else:
            prompt_tokens = int(total_chars / 1.5)  # 中文约 1.5 字符/token

        # 估算输出 token（翻译后通常长度变化）
        if lang_out == "zh":
            completion_tokens = int(prompt_tokens * 0.8)  # 中文译文通常较短
        else:
            completion_tokens = int(prompt_tokens * 1.2)

        costs = self.calculate_cost(prompt_tokens, completion_tokens, 0, model)

        return {
            "estimated_prompt_tokens": prompt_tokens,
            "estimated_completion_tokens": completion_tokens,
            "estimated_total_tokens": prompt_tokens + completion_tokens,
            "estimated_input_cost": costs["input_cost"],
            "estimated_output_cost": costs["output_cost"],
            "estimated_total_cost": costs["total_cost"],
            "model": model,
            "pricing": MODEL_PRICING.get(model, DEFAULT_PRICING),
        }

    def get_model_comparison(self, total_chars: int = 10000) -> list:
        """获取各模型成本对比"""
        comparisons = []
        for model in MODEL_PRICING:
            estimate = self.estimate_cost(total_chars, model)
            comparisons.append({
                "model": model,
                "total_tokens": estimate["estimated_total_tokens"],
                "total_cost": estimate["estimated_total_cost"],
                "input_price": estimate["pricing"]["input"],
                "output_price": estimate["pricing"]["output"],
            })

        comparisons.sort(key=lambda x: x["total_cost"])
        return comparisons

    def export_report(self, filepath: str, project: str = None):
        """导出成本报告"""
        summary = self.get_summary(project)

        report = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "summary": {
                "total_cost": round(summary.total_cost, 4),
                "total_tokens": summary.total_tokens,
                "total_prompt_tokens": summary.total_prompt_tokens,
                "total_completion_tokens": summary.total_completion_tokens,
                "total_cached_tokens": summary.total_cached_tokens,
                "cache_savings": round(
                    (summary.total_cached_tokens / 1000) *
                    (MODEL_PRICING.get("deepseek-chat", DEFAULT_PRICING)["input"] * 0.9), 4
                ),
                "record_count": summary.record_count,
            },
            "by_model": {
                k: {"cost": round(v["cost"], 4), "tokens": v["tokens"], "count": v["count"]}
                for k, v in summary.by_model.items()
            },
            "by_project": {
                k: {"cost": round(v["cost"], 4), "tokens": v["tokens"], "count": v["count"]}
                for k, v in summary.by_project.items()
            },
            "daily_trend": {
                k: {"cost": round(v["cost"], 4), "tokens": v["tokens"]}
                for k, v in summary.by_date.items()
            },
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        return report


# ============================================================
# 2. 多引擎对比翻译
# ============================================================

@dataclass
class TranslationCandidate:
    """翻译候选结果"""
    model: str
    translation: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    quality_score: float = 0.0
    cost: float = 0.0


class MultiEngineTranslator:
    """多引擎对比翻译器"""

    def __init__(self, engines: list = None):
        """
        Args:
            engines: [(model, base_url, api_key), ...]
        """
        self.engines = engines or []
        self.cost_analyzer = CostAnalyzer()

    def add_engine(self, model: str, base_url: str, api_key: str):
        """添加翻译引擎"""
        self.engines.append((model, base_url, api_key))

    def translate_concurrent(self, text: str, lang_in: str, lang_out: str,
                             timeout: int = 60) -> list:
        """
        并发调用多个引擎翻译

        Returns:
            TranslationCandidate 列表
        """
        import asyncio
        import httpx
        import openai

        async def call_engine(model, base_url, api_key):
            start_time = time.monotonic()
            try:
                client = openai.AsyncOpenAI(
                    base_url=base_url,
                    api_key=api_key,
                    http_client=httpx.AsyncClient(timeout=timeout),
                )

                response = await client.chat.completions.create(
                    model=model,
                    temperature=0,
                    messages=[
                        {"role": "system", "content": "You are a professional, authentic machine translation engine."},
                        {"role": "user", "content": f";; Treat next line as plain text input and translate it into {lang_out}, output translation ONLY. If translation is unnecessary (e.g. proper nouns, codes), return the original text. NO explanations. NO notes. Input:\n\n{text}"},
                    ],
                )

                elapsed_ms = (time.monotonic() - start_time) * 1000
                translation = response.choices[0].message.content.strip()

                # 计算成本
                prompt_tokens = response.usage.prompt_tokens if response.usage else 0
                completion_tokens = response.usage.completion_tokens if response.usage else 0
                costs = self.cost_analyzer.calculate_cost(
                    prompt_tokens, completion_tokens, 0, model
                )

                return TranslationCandidate(
                    model=model,
                    translation=translation,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=elapsed_ms,
                    cost=costs["total_cost"],
                )
            except Exception as e:
                elapsed_ms = (time.monotonic() - start_time) * 1000
                return TranslationCandidate(
                    model=model,
                    translation=f"[错误: {str(e)[:100]}]",
                    latency_ms=elapsed_ms,
                )

        async def run_all():
            tasks = [call_engine(m, u, k) for m, u, k in self.engines]
            return await asyncio.gather(*tasks, return_exceptions=True)

        loop = asyncio.new_event_loop()
        results = loop.run_until_complete(run_all())
        loop.close()

        # 过滤掉异常结果
        candidates = []
        for r in results:
            if isinstance(r, TranslationCandidate):
                candidates.append(r)

        return candidates

    def select_best(self, candidates: list, strategy: str = "quality") -> TranslationCandidate:
        """
        选择最佳翻译

        Args:
            candidates: 候选列表
            strategy: 选择策略 (quality/cost/latency/balanced)
        """
        if not candidates:
            return None

        valid = [c for c in candidates if not c.translation.startswith("[错误")]
        if not valid:
            return candidates[0]

        if strategy == "cost":
            return min(valid, key=lambda c: c.cost)
        elif strategy == "latency":
            return min(valid, key=lambda c: c.latency_ms)
        elif strategy == "quality":
            # 简单启发：选择长度中位数的翻译（避免极端长度）
            lengths = sorted(len(c.translation) for c in valid)
            median_len = lengths[len(lengths) // 2]
            return min(valid, key=lambda c: abs(len(c.translation) - median_len))
        else:  # balanced
            # 综合评分
            def balanced_score(c):
                cost_score = 1 / (1 + c.cost * 100)  # 成本越低越好
                latency_score = 1 / (1 + c.latency_ms / 1000)  # 延迟越低越好
                return cost_score + latency_score

            return max(valid, key=balanced_score)


# ============================================================
# 3. 自适应机器翻译 (AMT)
# ============================================================

@dataclass
class FeedbackEntry:
    """用户反馈条目"""
    id: int = 0
    source_text: str = ""
    original_translation: str = ""
    corrected_translation: str = ""
    model: str = ""
    lang_in: str = ""
    lang_out: str = ""
    feedback_type: str = ""  # correction/improvement/style
    timestamp: float = 0.0


class AdaptiveMT:
    """自适应机器翻译 - 从用户反馈中学习"""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "data" / "adaptive_mt.db"
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        with _safe_sqlite_connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_text TEXT NOT NULL,
                    original_translation TEXT NOT NULL,
                    corrected_translation TEXT NOT NULL,
                    model TEXT NOT NULL,
                    lang_in TEXT NOT NULL,
                    lang_out TEXT NOT NULL,
                    feedback_type TEXT DEFAULT 'correction',
                    timestamp REAL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_model ON feedback(model);
                CREATE INDEX IF NOT EXISTS idx_feedback_lang ON feedback(lang_in, lang_out);

                CREATE TABLE IF NOT EXISTS style_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern TEXT NOT NULL,
                    replacement TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    hit_count INTEGER DEFAULT 0,
                    timestamp REAL DEFAULT 0
                );
            """)

    def add_feedback(self, source: str, original: str, corrected: str,
                     model: str, lang_in: str, lang_out: str,
                     feedback_type: str = "correction"):
        """添加用户反馈"""
        with _safe_sqlite_connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO feedback
                (source_text, original_translation, corrected_translation,
                 model, lang_in, lang_out, feedback_type, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (source, original, corrected, model, lang_in, lang_out,
                  feedback_type, time.time()))

            # 尝试提取风格规则
            self._extract_rule(conn, original, corrected)

    def _extract_rule(self, conn, original: str, corrected: str):
        """从反馈中提取替换规则"""
        # 简单的差异检测：找出 original 和 corrected 中不同的词
        orig_words = original.split()
        corr_words = corrected.split()

        if len(orig_words) == len(corr_words):
            for ow, cw in zip(orig_words, corr_words):
                if ow != cw and len(ow) > 2:
                    # 检查是否已有此规则
                    existing = conn.execute(
                        "SELECT id FROM style_rules WHERE pattern = ? AND replacement = ?",
                        (ow, cw)
                    ).fetchone()

                    if existing:
                        conn.execute(
                            "UPDATE style_rules SET hit_count = hit_count + 1 WHERE id = ?",
                            (existing[0],)
                        )
                    else:
                        conn.execute("""
                            INSERT INTO style_rules (pattern, replacement, hit_count, timestamp)
                            VALUES (?, ?, 1, ?)
                        """, (ow, cw, time.time()))

    def get_style_rules(self, min_hits: int = 2) -> list:
        """获取高频风格规则"""
        with _safe_sqlite_connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM style_rules
                WHERE hit_count >= ?
                ORDER BY hit_count DESC
            """, (min_hits,)).fetchall()

        return [(r["pattern"], r["replacement"], r["hit_count"]) for r in rows]

    def apply_rules(self, text: str) -> str:
        """应用风格规则"""
        rules = self.get_style_rules(min_hits=2)
        result = text
        for pattern, replacement, _ in rules:
            result = result.replace(pattern, replacement)
        return result

    def get_adaptive_prompt_addon(self, lang_in: str, lang_out: str, model: str) -> str:
        """获取自适应提示附加内容"""
        rules = self.get_style_rules(min_hits=3)
        if not rules:
            return ""

        addon = "\n\n根据用户偏好，请使用以下翻译风格：\n"
        for pattern, replacement, hits in rules[:10]:
            addon += f'  - 将 "{pattern}" 翻译为 "{replacement}"\n'

        return addon

    def get_stats(self) -> dict:
        """获取统计信息"""
        with _safe_sqlite_connect(self.db_path) as conn:
            total_feedback = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
            total_rules = conn.execute("SELECT COUNT(*) FROM style_rules").fetchone()[0]
            top_rules = conn.execute("""
                SELECT pattern, replacement, hit_count FROM style_rules
                ORDER BY hit_count DESC LIMIT 5
            """).fetchall()

        return {
            "total_feedback": total_feedback,
            "total_rules": total_rules,
            "top_rules": [(r[0], r[1], r[2]) for r in top_rules],
        }


# ============================================================
# 4. 图片/OCR 翻译
# ============================================================

@dataclass
class OCRResult:
    """OCR 识别结果"""
    text: str
    confidence: float
    bbox: tuple  # (x, y, width, height)
    page_num: int = 0


class ImageTranslator:
    """图片/OCR 翻译器"""

    def __init__(self):
        self.supported_formats = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'}

    def detect_scanned_pdf(self, pdf_path: str) -> bool:
        """检测 PDF 是否为扫描件"""
        try:
            import pymupdf
            doc = pymupdf.open(pdf_path)

            # 检查前 3 页是否有文字
            text_pages = 0
            for i in range(min(3, len(doc))):
                page = doc[i]
                text = page.get_text().strip()
                if len(text) > 50:
                    text_pages += 1

            doc.close()
            # 如果前 3 页都没有足够文字，可能是扫描件
            return text_pages == 0
        except Exception:
            return False

    def extract_images_from_pdf(self, pdf_path: str) -> list:
        """从 PDF 提取图片"""
        import pymupdf
        doc = pymupdf.open(pdf_path)
        images = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            for img in page.get_images(full=True):
                xref = img[0]
                base_image = doc.extract_image(xref)
                if base_image:
                    images.append({
                        "page": page_num,
                        "xref": xref,
                        "ext": base_image["ext"],
                        "width": base_image["width"],
                        "height": base_image["height"],
                    })

        doc.close()
        return images

    def ocr_image(self, image_path: str, lang: str = "en") -> list:
        """
        对图片执行 OCR

        Returns:
            OCRResult 列表
        """
        try:
            import pymupdf
            # 使用 PyMuPDF 内置 OCR (需要 Tesseract)
            doc = pymupdf.open(image_path)
            results = []

            for page_num in range(len(doc)):
                page = page[page_num]
                # 获取文本块
                blocks = page.get_text("dict")["blocks"]
                for block in blocks:
                    if block["type"] == 0:  # 文本块
                        for line in block["lines"]:
                            text = "".join(span["text"] for span in line["spans"])
                            if text.strip():
                                bbox = line["bbox"]
                                results.append(OCRResult(
                                    text=text,
                                    confidence=0.9,  # PyMuPDF 不提供置信度
                                    bbox=bbox,
                                    page_num=page_num,
                                ))

            doc.close()
            return results
        except Exception as e:
            return [OCRResult(text=f"[OCR错误: {str(e)}]", confidence=0, bbox=(0, 0, 0, 0))]

    def ocr_pdf_page(self, pdf_path: str, page_num: int, lang: str = "en") -> list:
        """对 PDF 指定页执行 OCR"""
        try:
            import pymupdf
            doc = pymupdf.open(pdf_path)
            if page_num >= len(doc):
                return []

            page = doc[page_num]
            # 将页面转为图片
            pix = page.get_pixmap(dpi=300)
            img_data = pix.tobytes("png")

            # 临时保存图片进行 OCR
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(img_data)
                img_path = f.name

            results = self.ocr_image(img_path, lang)

            import os
            os.unlink(img_path)
            doc.close()

            return results
        except Exception as e:
            return [OCRResult(text=f"[OCR错误: {str(e)}]", confidence=0, bbox=(0, 0, 0, 0))]

    def translate_image_text(self, ocr_results: list, translator_func,
                             lang_in: str, lang_out: str) -> list:
        """
        翻译 OCR 识别结果

        Args:
            ocr_results: OCR 结果列表
            translator_func: 翻译函数 (text) -> translated_text
            lang_in: 源语言
            lang_out: 目标语言

        Returns:
            [(OCRResult, translated_text), ...]
        """
        translated = []
        for result in ocr_results:
            if result.text.strip():
                translation = translator_func(result.text)
                translated.append((result, translation))
        return translated

    def is_available(self) -> bool:
        """检查 OCR 功能是否可用"""
        try:
            import pymupdf
            return True
        except ImportError:
            return False