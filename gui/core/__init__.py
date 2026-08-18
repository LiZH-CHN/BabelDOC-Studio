"""
翻译质量与记忆模块
包含：翻译记忆库、术语库、QA 检查、质量评分、术语替换、高级翻译功能
"""

# 从子模块导入核心类（保持向后兼容）
from gui.core.translation_memory import TMEntry, TranslationMemory
from gui.core.glossary_manager import GlossaryEntry, GlossaryManager

# 导入术语替换和 AI 术语库模块
from gui.core.term_replacer import TermReplacer, TermInjector, SmartTermMatcher, create_default_replacer
from gui.core.ai_glossary import AI_CS_GLOSSARY, get_all_terms, get_terms_by_domain, get_domains, get_sub_domains
from gui.core.domain_detector import detect_domain, get_best_domain, get_all_domains

# 导入高级翻译功能模块
from gui.core.advanced_translation import (
    CostAnalyzer, CostRecord, CostSummary,
    MultiEngineTranslator, TranslationCandidate,
    AdaptiveMT, FeedbackEntry,
    ImageTranslator, OCRResult,
    MODEL_PRICING, DEFAULT_PRICING,
)

__all__ = [
    # 翻译记忆
    "TMEntry",
    "TranslationMemory",
    # 术语库
    "GlossaryEntry",
    "GlossaryManager",
    # 术语替换
    "TermReplacer",
    "TermInjector",
    "SmartTermMatcher",
    "create_default_replacer",
    # AI 术语库
    "AI_CS_GLOSSARY",
    "get_all_terms",
    "get_terms_by_domain",
    "get_domains",
    "get_sub_domains",
    # 领域检测
    "detect_domain",
    "get_best_domain",
    "get_all_domains",
    # 高级翻译功能
    "CostAnalyzer",
    "CostRecord",
    "CostSummary",
    "MultiEngineTranslator",
    "TranslationCandidate",
    "AdaptiveMT",
    "FeedbackEntry",
    "ImageTranslator",
    "OCRResult",
    "MODEL_PRICING",
    "DEFAULT_PRICING",
]
