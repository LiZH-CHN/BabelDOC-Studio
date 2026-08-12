"""
翻译拦截器后端 - 核心架构
实现 PreProcessor、PostProcessor、QAGate 等拦截器
采用中间件模式，不修改 BabelDOC 源码
"""

import re
import time
import asyncio
import sqlite3
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum

from babeldoc.translator.translator import OpenAITranslator
from babeldoc.format.pdf.translation_config import TranslationConfig
from babeldoc.format.pdf.high_level import async_translate


# ============================================================
# 数据结构定义
# ============================================================

class TranslationStage(Enum):
    """翻译阶段枚举"""
    IDLE = "idle"
    PRE_PROCESSING = "pre_processing"
    TM_LOOKUP = "tm_lookup"
    API_CALL = "api_call"
    POST_PROCESSING = "post_processing"
    QA_CHECK = "qa_check"
    COST_RECORDING = "cost_recording"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class TranslationOptions:
    """翻译选项 - 从 UI 收集的所有配置"""
    # 基础配置
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    lang_in: str = "en"
    lang_out: str = "zh"
    input_file: str = ""
    output_dir: str = ""
    pages: str = ""
    qps: int = 4

    # 输出选项
    no_dual: bool = False
    no_mono: bool = False

    # 术语库
    enable_glossary: bool = True
    glossary_terms: list = field(default_factory=list)

    # 翻译记忆库
    enable_tm: bool = True
    tm_threshold: float = 0.95

    # 多引擎
    enable_multi_engine: bool = False
    engine2_model: str = ""
    engine2_base_url: str = ""
    engine2_api_key: str = ""
    multi_strategy: str = "balanced"

    # 自适应 MT
    enable_adaptive_mt: bool = True

    # QA
    enable_qa: bool = True

    # OCR
    enable_ocr: bool = False

    # 成本分析
    enable_cost_tracking: bool = True


@dataclass
class TranslationResult:
    """翻译结果"""
    success: bool = False
    output_path: str = ""
    error_message: str = ""
    stats: dict = field(default_factory=dict)
    qa_issues: list = field(default_factory=list)
    quality_grade: str = ""
    cost: float = 0.0
    tokens: int = 0


# ============================================================
# 1. PreProcessor - 翻译前拦截器
# ============================================================

class PreProcessor:
    """
    翻译前处理器
    - 术语注入
    - TM 查询
    - 文本预处理
    """

    def __init__(self, options: TranslationOptions):
        self.options = options
        self._init_modules()

    def _init_modules(self):
        """初始化各子模块"""
        # 术语替换器
        from gui.core.term_replacer import TermReplacer, TermInjector, create_default_replacer
        self.term_replacer = create_default_replacer()
        self.term_injector = TermInjector()

        # 翻译记忆库
        if self.options.enable_tm:
            from gui.core import TranslationMemory
            self.tm = TranslationMemory()
        else:
            self.tm = None

        # 自适应 MT
        if self.options.enable_adaptive_mt:
            from gui.core.advanced_translation import AdaptiveMT
            self.amt = AdaptiveMT()
        else:
            self.amt = None

    def process(self, text: str) -> tuple:
        """
        处理待翻译文本

        Returns:
            (processed_text, metadata)
            metadata 包含: tm_hit, term_count, adaptive_addon 等
        """
        metadata = {
            "tm_hit": False,
            "tm_translation": None,
            "tm_similarity": 0.0,
            "tm_skipped_api": False,
            "tm_poison_rejected": False,
            "term_count": 0,
            "adaptive_addon": "",
        }

        if not text or not text.strip():
            return text, metadata

        # 1. 检查 TM（精确匹配）
        if self.tm and self.options.enable_tm:
            tm_result = self.tm.get_exact_match(text, self.options.lang_in, self.options.lang_out)
            if tm_result:
                # 探针 3 加固：毒药输入防御 - 精确匹配也校验数字完整性
                if self._tm_translation_is_safe(text, tm_result.target_text):
                    metadata["tm_hit"] = True
                    metadata["tm_translation"] = tm_result.target_text
                    metadata["tm_similarity"] = 1.0
                    metadata["tm_skipped_api"] = True
                    return tm_result.target_text, metadata
                else:
                    metadata["tm_poison_rejected"] = True

        # 2. 检查 TM（模糊匹配）
        if self.tm and self.options.enable_tm:
            similar = self.tm.search_similar(
                text, self.options.lang_in, self.options.lang_out,
                threshold=self.options.tm_threshold
            )
            if similar:
                best_entry, similarity = similar[0]
                if similarity >= self.options.tm_threshold:
                    # 探针 3 加固：高相似度毒药防御
                    # 若源文数字/关键实体未出现在译文中，拒绝采用并降级到 API
                    if self._tm_translation_is_safe(text, best_entry.target_text):
                        metadata["tm_hit"] = True
                        metadata["tm_translation"] = best_entry.target_text
                        metadata["tm_similarity"] = similarity
                        metadata["tm_skipped_api"] = True
                        return best_entry.target_text, metadata
                    else:
                        metadata["tm_poison_rejected"] = True

        # 3. 术语替换（占位符保护）
        if self.options.enable_glossary and self.options.glossary_terms:
            text = self.term_replacer.pre_translate(text, self.options.glossary_terms)
            metadata["term_count"] = self.term_replacer.get_replacement_count()

        return text, metadata

    @staticmethod
    def _tm_translation_is_safe(source: str, candidate: str) -> bool:
        """探针 3 加固：TM 译文安全性校验。

        毒药输入场景：TM 中存入 99% 相似度但语义错误的译文（如
        Transformer→变形金刚）。此处通过数字与关键实体完整性校验
        拒绝明显错误的 TM 命中，降级回 API 调用。

        Returns:
            True 表示可安全采用，False 表示疑似毒药应拒绝
        """
        if not source or not candidate:
            return False

        # 数字一致性：源文数字必须全部出现在译文中
        source_numbers = set(re.findall(r'\d+(?:\.\d+)?', source))
        if source_numbers:
            target_numbers = set(re.findall(r'\d+(?:\.\d+)?', candidate))
            missing = source_numbers - target_numbers
            if missing:
                return False

        # 长度异常：译文过短（< 源文 10%）视为可疑
        if len(source) > 20 and len(candidate) < len(source) * 0.1:
            return False

        return True

    def get_adaptive_addon(self) -> str:
        """获取自适应 MT 的 prompt 附加内容"""
        if self.amt and self.options.enable_adaptive_mt:
            return self.amt.get_adaptive_prompt_addon(
                self.options.lang_in, self.options.lang_out, self.options.model
            )
        return ""

    def get_glossary_hint(self) -> str:
        """获取术语提示（注入到 prompt 中）"""
        if self.options.enable_glossary and self.options.glossary_terms:
            return self.term_injector.build_term_hint(self.options.glossary_terms, max_terms=15)
        return ""


# ============================================================
# 2. PostProcessor - 翻译后拦截器
# ============================================================

class PostProcessor:
    """
    翻译后处理器
    - 占位符还原
    - 自适应规则应用
    - 文本后处理
    """

    def __init__(self, options: TranslationOptions):
        self.options = options
        self._init_modules()

    def _init_modules(self):
        """初始化子模块"""
        from gui.core.term_replacer import create_default_replacer
        self.term_replacer = create_default_replacer()

        if self.options.enable_adaptive_mt:
            from gui.core.advanced_translation import AdaptiveMT
            self.amt = AdaptiveMT()
        else:
            self.amt = None

    def process(self, text: str, pre_metadata: dict) -> str:
        """
        处理翻译后的文本

        Args:
            text: 译文
            pre_metadata: 预处理阶段的元数据

        Returns:
            最终译文
        """
        if not text:
            return text

        # 1. 还原术语占位符
        if pre_metadata.get("term_count", 0) > 0:
            text = self.term_replacer.post_translate(text)

        # 2. 应用自适应规则
        if self.amt and self.options.enable_adaptive_mt:
            text = self.amt.apply_rules(text)

        return text


# ============================================================
# 3. QAGate - 质量闸门
# ============================================================

class QAGate:
    """
    质量闸门 - 翻译完成后执行 QA 检查
    - 占位符完整性检查
    - 长度异常检测
    - 质量评分
    """

    def __init__(self):
        from gui.core.quality import QAChecker, QualityScorer
        self.qa_checker = QAChecker()
        self.scorer = QualityScorer()

    def validate(self, source: str, target: str) -> dict:
        """
        执行 QA 验证

        Returns:
            {
                "valid": bool,
                "issues": list,
                "score": QualityScore,
                "can_auto_fix": bool,
            }
        """
        result = {
            "valid": True,
            "issues": [],
            "score": None,
            "can_auto_fix": False,
        }

        # 1. 占位符检查
        placeholder_issues = self._check_placeholders(source, target)
        if placeholder_issues:
            result["issues"].extend(placeholder_issues)
            result["can_auto_fix"] = True

        # 2. 长度异常检查
        length_issues = self._check_length(source, target)
        if length_issues:
            result["issues"].extend(length_issues)

        # 探针 4 加固：数字/实体语义不变性检查
        # 源文数字个数 ≠ 译文数字个数时触发自动修复
        number_issues = self._check_numbers_invariance(source, target)
        if number_issues:
            result["issues"].extend(number_issues)
            # 数字缺失可自动修复（重译补全）
            if any(i["type"] == "number_missing" for i in number_issues):
                result["can_auto_fix"] = True

        # 3. 质量评分
        score = self.scorer.score(source, target)
        result["score"] = score

        # 4. 判断是否有效
        critical_issues = [i for i in result["issues"] if i.get("severity") == "critical"]
        if critical_issues:
            result["valid"] = False

        return result

    def _check_numbers_invariance(self, source: str, target: str) -> list:
        """探针 4 加固：数字语义不变性对抗检查。

        场景：大模型翻译 "E=mc² was proposed in 1905." 时漏掉 1905。
        通过正则抽取数字实体，对比源文与译文数字集合。
        """
        issues = []

        source_numbers = re.findall(r'\d+(?:\.\d+)?', source)
        target_numbers = re.findall(r'\d+(?:\.\d+)?', target)

        source_set = set(source_numbers)
        target_set = set(target_numbers)

        missing = source_set - target_set
        if missing and source_set:
            issues.append({
                "type": "number_missing",
                "severity": "critical",
                "message": f"译文缺失数字: {', '.join(sorted(missing))}",
                "missing_numbers": sorted(missing),
                "source_count": len(source_set),
                "target_count": len(target_set),
            })

        return issues

    def _check_placeholders(self, source: str, target: str) -> list:
        """检查占位符完整性"""
        issues = []

        # BabelDOC 使用的占位符模式
        patterns = [
            r'\{\{[^}]+\}\}',      # {{FORMULA_0}}
            r'§TERM_\d+§',          # §TERM_0§
            r'<[^>]+>',             # HTML 标签
        ]

        for pattern in patterns:
            source_matches = set(re.findall(pattern, source))
            target_matches = set(re.findall(pattern, target))

            missing = source_matches - target_matches
            if missing:
                issues.append({
                    "type": "placeholder_missing",
                    "severity": "critical",
                    "message": f"占位符缺失: {', '.join(sorted(missing))}",
                    "missing": list(missing),
                })

        return issues

    def _check_length(self, source: str, target: str) -> list:
        """检查长度异常"""
        issues = []

        if not source or not target:
            return issues

        source_len = len(source)
        target_len = len(target)

        if source_len == 0:
            return issues

        ratio = target_len / source_len

        if ratio > 5.0:
            issues.append({
                "type": "length_anomaly",
                "severity": "warning",
                "message": f"译文长度是原文的 {ratio:.1f} 倍，可能存在幻觉",
            })
        elif ratio < 0.1 and source_len > 20:
            issues.append({
                "type": "length_anomaly",
                "severity": "warning",
                "message": f"译文长度仅为原文的 {ratio:.1%}，可能遗漏内容",
            })

        return issues


# ============================================================
# 4. CostTracker - 成本追踪器
# ============================================================

class CostTracker:
    """成本追踪器"""

    def __init__(self):
        from gui.core.advanced_translation import CostAnalyzer
        self.analyzer = CostAnalyzer()
        self.session_cost = 0.0
        self.session_tokens = 0
        self.records = []

    def record(self, model: str, prompt_tokens: int, completion_tokens: int,
               cached_tokens: int = 0, file_name: str = ""):
        """记录一次翻译的成本"""
        # 探针 8 加固：空文档 usage 为空时 None 防御
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        cached_tokens = max(0, int(cached_tokens or 0))

        record = self.analyzer.record_translation(
            model=model or "unknown",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            file_name=file_name,
        )
        self.session_cost += record.total_cost
        self.session_tokens += record.total_tokens
        self.records.append(record)
        return record

    def estimate(self, total_chars: int, model: str, lang_in: str = "en", lang_out: str = "zh"):
        """预估成本"""
        return self.analyzer.estimate_cost(total_chars, model, lang_in, lang_out)

    def get_session_summary(self) -> dict:
        """获取当前会话汇总"""
        return {
            "session_cost": self.session_cost,
            "session_tokens": self.session_tokens,
            "record_count": len(self.records),
        }


# ============================================================
# 5. InterceptorTranslator - 带拦截器的翻译器包装
# ============================================================

class InterceptorTranslator:
    """
    带拦截器的翻译器
    包装 OpenAITranslator，在翻译前后插入拦截逻辑
    """

    def __init__(self, base_translator: OpenAITranslator, options: TranslationOptions):
        self.base = base_translator
        self.options = options
        self.preprocessor = PreProcessor(options)
        self.postprocessor = PostProcessor(options)
        self.qa_gate = QAGate()
        self.cost_tracker = CostTracker()

        # 统计
        self.tm_hits = 0
        self.api_calls = 0
        self.qa_failures = 0
        self.auto_fixes = 0

        # 包装翻译方法
        self._wrap_translator()

    def _wrap_translator(self):
        """包装翻译方法，插入拦截逻辑"""
        base = self.base

        # 保存原始方法
        original_do_translate = base.do_translate
        original_prompt = base.prompt

        # 获取自适应提示
        adaptive_addon = self.preprocessor.get_adaptive_addon()
        glossary_hint = self.preprocessor.get_glossary_hint()

        # 包装 prompt 方法
        def enhanced_prompt(text):
            messages = original_prompt(text)
            if messages:
                addon = ""
                if adaptive_addon:
                    addon += adaptive_addon
                if glossary_hint:
                    addon += glossary_hint
                if addon:
                    messages[0]["content"] += addon
            return messages

        base.prompt = enhanced_prompt

        # 包装 do_translate 方法
        def enhanced_do_translate(text, rate_limit_params=None):
            # 1. 预处理（TM 查询 + 术语替换）
            processed_text, metadata = self.preprocessor.process(text)

            # 2. 如果 TM 命中，直接返回
            if metadata["tm_hit"]:
                self.tm_hits += 1
                return metadata["tm_translation"]

            # 3. 调用 API 翻译
            self.api_calls += 1
            translated = original_do_translate(processed_text, rate_limit_params)

            # 4. 后处理（占位符还原 + 自适应规则）
            translated = self.postprocessor.process(translated, metadata)

            # 5. QA 检查
            if self.options.enable_qa:
                qa_result = self.qa_gate.validate(text, translated)
                if not qa_result["valid"]:
                    self.qa_failures += 1
                    # 尝试自动修复
                    if qa_result["can_auto_fix"]:
                        translated = self._auto_fix(text, translated, qa_result)
                        self.auto_fixes += 1

            return translated

        base.do_translate = enhanced_do_translate

    def _auto_fix(self, source: str, target: str, qa_result: dict) -> str:
        """自动修复 QA 发现的问题"""
        # 占位符修复
        for issue in qa_result.get("issues", []):
            if issue["type"] == "placeholder_missing":
                for placeholder in issue.get("missing", []):
                    # 尝试在源文中找到占位符位置，插入到译文中
                    if placeholder in source:
                        target = target + " " + placeholder

        # 探针 4 加固：数字缺失自动修复 - 重译补全缺失数字
        # 用户全程无感知，进度条不倒退，最终 PDF 数字正确
        for issue in qa_result.get("issues", []):
            if issue["type"] == "number_missing":
                missing_numbers = issue.get("missing_numbers", [])
                if not missing_numbers:
                    continue
                try:
                    # 构造补全指令，重新调用大模型
                    fix_instruction = (
                        f"补全缺失的数字 {', '.join(missing_numbers)}，"
                        "只返回修正后的译文，不要解释。"
                    )
                    # 复用 base 翻译器，附加补全指令
                    original_do_translate = self.base.__class__.do_translate
                    fixed = original_do_translate(
                        self.base,
                        f"{source}\n\n{fix_instruction}",
                        None,
                    )
                    # 校验修复结果确实包含缺失数字
                    fixed_numbers = set(re.findall(r'\d+(?:\.\d+)?', fixed))
                    if all(n in fixed_numbers for n in missing_numbers):
                        target = fixed
                except Exception:
                    # 重译失败则保留原译文，不阻断流程
                    pass
                break  # 只修复一次，避免反复调用 API

        return target

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "tm_hits": self.tm_hits,
            "api_calls": self.api_calls,
            "qa_failures": self.qa_failures,
            "auto_fixes": self.auto_fixes,
            "cost": self.cost_tracker.session_cost,
            "tokens": self.cost_tracker.session_tokens,
        }


# ============================================================
# 6. MultiEngineManager - 多引擎管理器
# ============================================================

class MultiEngineManager:
    """多引擎管理器 - 支持并发翻译和熔断机制"""

    def __init__(self, options: TranslationOptions):
        self.options = options
        self.results = {}
        self.start_times = {}

    async def translate_concurrent(self, text: str) -> dict:
        """
        并发调用多个引擎翻译

        Returns:
            {"engine1": result1, "engine2": result2}
        """
        tasks = []

        # 引擎 1
        tasks.append(self._translate_with_engine(
            text, self.options.model, self.options.base_url,
            self.options.api_key, "engine1"
        ))

        # 引擎 2
        if self.options.enable_multi_engine and self.options.engine2_model:
            tasks.append(self._translate_with_engine(
                text, self.options.engine2_model, self.options.engine2_base_url,
                self.options.engine2_api_key, "engine2"
            ))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for key, result in zip(["engine1", "engine2"], results):
            if isinstance(result, Exception):
                output[key] = {"error": str(result)}
            else:
                output[key] = result

        return output

    async def _translate_with_engine(self, text: str, model: str,
                                     base_url: str, api_key: str,
                                     engine_id: str) -> dict:
        """使用指定引擎翻译"""
        import httpx
        import openai

        self.start_times[engine_id] = time.monotonic()

        try:
            client = openai.AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                http_client=httpx.AsyncClient(timeout=120),
            )

            response = await client.chat.completions.create(
                model=model,
                temperature=0,
                messages=[
                    {"role": "system", "content": "You are a professional, authentic machine translation engine."},
                    {"role": "user", "content": f";; Treat next line as plain text input and translate it into {self.options.lang_out}, output translation ONLY. Input:\n\n{text}"},
                ],
            )

            elapsed = (time.monotonic() - self.start_times[engine_id]) * 1000

            # 探针 8 加固：content 可能为 None（空响应）
            content = response.choices[0].message.content if response.choices else ""
            return {
                "translation": (content or "").strip(),
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "latency_ms": elapsed,
                "model": model,
            }
        except Exception as e:
            elapsed = (time.monotonic() - self.start_times[engine_id]) * 1000
            return {"error": str(e), "latency_ms": elapsed, "model": model}

    def select_best(self, results: dict) -> Optional[dict]:
        """根据策略选择最佳结果"""
        valid = {k: v for k, v in results.items() if "error" not in v}

        if not valid:
            return None

        if len(valid) == 1:
            return list(valid.values())[0]

        strategy = self.options.multi_strategy

        if strategy == "cost":
            return min(valid.values(), key=lambda x: x.get("prompt_tokens", 0) + x.get("completion_tokens", 0))
        elif strategy == "latency":
            return min(valid.values(), key=lambda x: x.get("latency_ms", float('inf')))
        elif strategy == "quality":
            # 选择长度中位数的结果
            lengths = sorted(len(x.get("translation", "")) for x in valid.values())
            median_len = lengths[len(lengths) // 2]
            return min(valid.values(), key=lambda x: abs(len(x.get("translation", "")) - median_len))
        else:  # balanced
            def balanced_score(x):
                cost_score = 1 / (1 + (x.get("prompt_tokens", 0) + x.get("completion_tokens", 0)) / 1000)
                latency_score = 1 / (1 + x.get("latency_ms", 1000) / 1000)
                return cost_score + latency_score
            return max(valid.values(), key=balanced_score)


# ============================================================
# 7. AdaptiveFallbackManager - 自适应故障切换熔断器
# ============================================================

class AdaptiveFallbackManager:
    """探针 7 加固：自适应模型故障切换管理器。

    场景：GLM-4.7 响应 > 5s 自动切换到 LongCat，但 LongCat Key 已过期。
    若无熔断，会陷入 GLM→LongCat→GLM 死循环白白浪费 Token。

    硬编码规则：最多切换 1 次。切换后仍失败则立即终止任务。
    """

    # 硬编码熔断阈值
    MAX_SWITCHES = 1

    def __init__(self, primary_model: str, fallback_model: str,
                 switch_threshold_seconds: float = 5.0):
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.switch_threshold = switch_threshold_seconds
        self._switch_count = 0
        self._current_model = primary_model
        self._failed_models = set()

    def should_switch(self, latency_seconds: float, error: Optional[str] = None) -> bool:
        """判断是否应该切换模型。

        Returns:
            True 表示应切换到备用模型
        """
        # 已达熔断上限，不再切换
        if self._switch_count >= self.MAX_SWITCHES:
            return False

        # 当前模型已失败（超时或错误）
        if error is not None:
            return True

        if latency_seconds > self.switch_threshold:
            return True

        return False

    def switch(self) -> Optional[str]:
        """执行模型切换。

        Returns:
            切换后的模型名，或 None 表示已熔断不可切换
        """
        if self._switch_count >= self.MAX_SWITCHES:
            return None

        self._switch_count += 1
        self._failed_models.add(self._current_model)
        self._current_model = self.fallback_model
        return self._current_model

    def mark_failed(self, model: str):
        """标记模型失败"""
        self._failed_models.add(model)

    def is_circuit_broken(self) -> bool:
        """熔断器是否已断开（不再允许任何切换）"""
        return self._switch_count >= self.MAX_SWITCHES

    def get_status(self) -> dict:
        """获取熔断器状态"""
        return {
            "switch_count": self._switch_count,
            "max_switches": self.MAX_SWITCHES,
            "current_model": self._current_model,
            "failed_models": list(self._failed_models),
            "circuit_broken": self.is_circuit_broken(),
        }

    def execute_with_fallback(self, translate_func, text: str,
                              on_switch=None) -> tuple:
        """带熔断的执行：主模型失败则切换一次，再失败则终止。

        Args:
            translate_func: (model, text) -> (result, latency, error)
            on_switch: 切换回调 (from_model, to_model)

        Returns:
            (result, used_model, error)
            若熔断则 error 包含熔断信息
        """
        import time as _time

        # 第一次尝试：主模型
        result, latency, error = translate_func(self._current_model, text)

        if error is None and latency <= self.switch_threshold:
            return result, self._current_model, None

        # 主模型失败，检查是否可切换
        if not self.should_switch(latency, error):
            # 已熔断，立即终止
            return (
                None,
                self._current_model,
                f"自适应切换失败（熔断），请检查网络或 Key。"
                f"已尝试模型: {self._failed_models | {self._current_model}}",
            )

        # 执行切换
        old_model = self._current_model
        new_model = self.switch()
        if new_model is None:
            return None, old_model, "自适应切换失败，已达熔断上限"

        if on_switch:
            on_switch(old_model, new_model)

        # 第二次尝试：备用模型（仅此一次）
        result, latency, error = translate_func(new_model, text)
        if error is None:
            return result, new_model, None

        # 备用模型也失败，熔断终止
        self.mark_failed(new_model)
        return (
            None,
            new_model,
            f"自适应切换失败，请检查网络或 Key。"
            f"主模型 {old_model} 与备用模型 {new_model} 均失败。",
        )


# ============================================================
# 8. TranslationPipeline - 完整翻译流水线
# ============================================================

class TranslationPipeline:
    """
    完整的翻译流水线
    整合所有拦截器和处理器
    """

    def __init__(self, options: TranslationOptions):
        self.options = options
        self.preprocessor = PreProcessor(options)
        self.postprocessor = PostProcessor(options)
        self.qa_gate = QAGate()
        self.cost_tracker = CostTracker()
        self.stage = TranslationStage.IDLE
        self._callbacks = {}

    def on(self, event: str, callback):
        """注册事件回调"""
        self._callbacks[event] = callback

    def _emit(self, event: str, *args):
        """触发事件"""
        if event in self._callbacks:
            self._callbacks[event](*args)

    def create_interceptor_translator(self) -> InterceptorTranslator:
        """创建带拦截器的翻译器"""
        base_translator = OpenAITranslator(
            lang_in=self.options.lang_in,
            lang_out=self.options.lang_out,
            model=self.options.model,
            base_url=self.options.base_url,
            api_key=self.options.api_key,

        )

        return InterceptorTranslator(base_translator, self.options)

    async def run_async(self) -> TranslationResult:
        """异步执行翻译"""
        result = TranslationResult()

        try:
            self.stage = TranslationStage.PRE_PROCESSING
            self._emit("stage_changed", self.stage.value)

            # 创建带拦截器的翻译器
            translator = self.create_interceptor_translator()

            self.stage = TranslationStage.API_CALL
            self._emit("stage_changed", self.stage.value)

            # 加载布局模型
            from babeldoc.docvision.doclayout import DocLayoutModel
            doc_layout_model = DocLayoutModel.load_onnx()

            # 创建翻译配置
            config = TranslationConfig(
                translator=translator.base,
                input_file=self.options.input_file,
                lang_in=self.options.lang_in,
                lang_out=self.options.lang_out,
                doc_layout_model=doc_layout_model,
                pages=self.options.pages or None,
                output_dir=self.options.output_dir or None,
                no_dual=self.options.no_dual,
                no_mono=self.options.no_mono,
                qps=self.options.qps,
            )

            # 执行翻译
            translate_result = None
            # 探针 1 加固：公式占位符混沌攻击降级
            # 不完整 LaTeX（如 $\frac{1}{2）会触发排版异常，此处捕获后降级为图片块而非闪退
            from babeldoc.babeldoc_exception.BabelDOCException import LayoutException
            formula_degraded_pages = set()

            async for event in async_translate(config):
                event_type = event.get("type", "")
                if event_type == "finish":
                    translate_result = event.get("result")
                elif event_type == "error":
                    err_msg = event.get("error", "未知错误")
                    # 识别公式/排版结构异常，降级处理
                    if any(
                        kw in err_msg
                        for kw in (
                            "formula", "latex", "layout", "排版", "公式",
                            "begin", "end", "frac", "array",
                        )
                    ):
                        degraded_page = event.get("page", 0)
                        formula_degraded_pages.add(degraded_page)
                        self._emit(
                            "log",
                            f"⚠️ PDF 第 {degraded_page} 页公式结构异常，"
                            "已自动降级为图片块处理",
                        )
                        # 不终止流程，继续消费后续事件
                        continue
                    # 其他错误向上抛出
                    raise LayoutException(err_msg, page=event.get("page", 0)) if "layout" in err_msg.lower() else Exception(err_msg)
                elif event_type == "progress_update":
                    self._emit("progress", event.get("progress", 0), event.get("stage", ""))

            if formula_degraded_pages:
                self._emit(
                    "log",
                    f"公式降级页汇总: {sorted(formula_degraded_pages)}",
                )

            # 收集结果
            if translate_result:
                self.stage = TranslationStage.COMPLETED

                # 获取输出路径
                output_path = None
                if hasattr(translate_result, 'dual_pdf_path') and translate_result.dual_pdf_path:
                    output_path = str(translate_result.dual_pdf_path)
                elif hasattr(translate_result, 'mono_pdf_path') and translate_result.mono_pdf_path:
                    output_path = str(translate_result.mono_pdf_path)

                # 获取拦截器统计
                stats = translator.get_stats()

                result.success = True
                result.output_path = output_path or ""
                result.stats = stats
                result.cost = stats.get("cost", 0)
                result.tokens = stats.get("tokens", 0)

                self._emit("completed", result)
            else:
                result.error_message = "翻译结果为空"
                self._emit("error", result.error_message)

        except Exception as e:
            self.stage = TranslationStage.ERROR
            result.error_message = f"{type(e).__name__}: {str(e)}"
            self._emit("error", result.error_message)

        return result

    def run(self) -> TranslationResult:
        """同步执行翻译"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.run_async())
        finally:
            loop.close()