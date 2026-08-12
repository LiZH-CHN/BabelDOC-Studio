"""
术语自动替换引擎
在翻译前后自动处理术语，确保术语一致性
"""

import re
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class TermReplacement:
    """术语替换记录"""
    original_term: str       # 原文中的术语
    placeholder: str         # 占位符
    translation: str         # 目标翻译
    position: int            # 在文本中的位置
    case_sensitive: bool     # 是否区分大小写


class TermReplacer:
    """术语替换器 - 翻译前替换为占位符，翻译后还原"""

    # LaTeX 公式块保护正则：避免术语替换器破坏 \begin{...}...\end{...} 结构
    _LATEX_BLOCK_PATTERN = re.compile(
        r'\\begin\{[^}]+\}.*?\\end\{[^}]+\}',
        re.DOTALL,
    )
    # 行内公式 $...$ 与 $$...$$（非贪婪，避免吞掉整段）
    _LATEX_INLINE_PATTERN = re.compile(r'\$\$?.*?\$\$?', re.DOTALL)

    def __init__(self):
        self.placeholder_prefix = "§TERM_"
        self.placeholder_suffix = "§"
        self._replacements = []
        self._placeholder_map = {}
        # 公式块保护表：保护占位符 -> 原始公式文本
        self._formula_protection = {}

    def reset(self):
        """重置替换状态"""
        self._replacements = []
        self._placeholder_map = {}
        self._formula_protection = {}

    def _protect_formulas(self, text: str) -> str:
        """将 LaTeX 公式块替换为保护占位符，避免术语替换干扰公式结构。

        探针 2 加固：表格内嵌公式 / 不完整 LaTeX 进入术语替换器会导致
        \\begin{array} 等渲染代码被误送入大模型，Token 暴涨且破坏结构。
        """
        if not text:
            return text

        protected = text
        idx = 0

        for pattern in (self._LATEX_BLOCK_PATTERN, self._LATEX_INLINE_PATTERN):
            for match in pattern.finditer(protected):
                original = match.group()
                # 跳过过短的匹配（避免误伤单独的 $ 符号）
                if len(original) < 3:
                    continue
                guard = f"§FORMULA_{idx}§"
                self._formula_protection[guard] = original
                protected = protected.replace(original, guard, 1)
                idx += 1

        return protected

    def _restore_formulas(self, text: str) -> str:
        """还原被保护的公式块"""
        if not text or not self._formula_protection:
            return text
        for guard, original in self._formula_protection.items():
            text = text.replace(guard, original)
        return text

    def pre_translate(self, text: str, terms: list) -> str:
        """
        翻译前：将术语替换为占位符

        Args:
            text: 源文本
            terms: GlossaryEntry 列表

        Returns:
            替换后的文本
        """
        self.reset()
        if not terms:
            return text

        # 探针 2 加固：先保护 LaTeX 公式块，术语替换仅在纯文本区域进行
        text = self._protect_formulas(text)

        # 按术语长度降序排列（先替换长的，避免短词干扰）
        sorted_terms = sorted(terms, key=lambda t: len(t.term), reverse=True)

        result = text
        index = 0

        for term_entry in sorted_terms:
            term = term_entry.term
            if not term:
                continue

            # 构建匹配模式
            if term_entry.case_sensitive:
                pattern = re.escape(term)
            else:
                pattern = re.escape(term)
                pattern = f"(?i:{pattern})"

            # 查找所有匹配
            for match in re.finditer(pattern, result):
                original = match.group()

                # 生成占位符
                placeholder = f"{self.placeholder_prefix}{index}{self.placeholder_suffix}"

                # 记录替换
                replacement = TermReplacement(
                    original_term=original,
                    placeholder=placeholder,
                    translation=term_entry.translation,
                    position=match.start(),
                    case_sensitive=term_entry.case_sensitive,
                )
                self._replacements.append(replacement)
                self._placeholder_map[placeholder] = term_entry.translation

                index += 1

        # 执行替换（从后往前替换，避免位置变化）
        for replacement in sorted(self._replacements, key=lambda r: r.position, reverse=True):
            # 使用正则精确替换
            pattern = re.escape(replacement.original_term)
            if not replacement.case_sensitive:
                pattern = f"(?i:{pattern})"

            # 只替换第一次出现
            result = re.sub(
                pattern,
                replacement.placeholder,
                result,
                count=1,
                flags=re.IGNORECASE if not replacement.case_sensitive else 0
            )

        return result

    def post_translate(self, text: str) -> str:
        """
        翻译后：将占位符替换为术语翻译

        Args:
            text: 译文（包含占位符）

        Returns:
            最终译文
        """
        result = text

        # 替换所有占位符
        for placeholder, translation in self._placeholder_map.items():
            result = result.replace(placeholder, translation)

        # 处理可能的残留占位符（如果翻译过程中占位符被修改）
        # 使用正则匹配所有占位符模式
        pattern = re.escape(self.placeholder_prefix) + r"(\d+)" + re.escape(self.placeholder_suffix)

        def replace_match(match):
            placeholder = match.group(0)
            idx = int(match.group(1))
            if idx < len(self._replacements):
                return self._replacements[idx].translation
            return placeholder  # 保留未识别的占位符

        result = re.sub(pattern, replace_match, result)

        # 探针 2 加固：还原被保护的 LaTeX 公式块
        result = self._restore_formulas(result)

        return result

    def get_replacement_count(self) -> int:
        """获取替换的术语数量"""
        return len(self._replacements)


class TermInjector:
    """术语注入器 - 在 prompt 中添加术语指导"""

    @staticmethod
    def build_term_hint(terms: list, max_terms: int = 20) -> str:
        """
        构建术语提示

        Args:
            terms: GlossaryEntry 列表
            max_terms: 最大术语数

        Returns:
            术语提示字符串
        """
        if not terms:
            return ""

        selected_terms = terms[:max_terms]

        hints = ["\n\n术语表（请严格使用以下翻译）："]
        for term in selected_terms:
            hints.append(f'  "{term.term}" → "{term.translation}"')

        if len(terms) > max_terms:
            hints.append(f"  ... 还有 {len(terms) - max_terms} 条术语")

        return "\n".join(hints)

    @staticmethod
    def build_system_prompt_addon(terms: list, domain: str = "") -> str:
        """构建系统提示中的术语指导"""
        if not terms:
            return ""

        addon_parts = []
        if domain:
            addon_parts.append(f"你正在翻译{domain}领域的文档。")

        addon_parts.append("请使用以下术语翻译：")
        for term in terms[:15]:
            addon_parts.append(f"  - {term.term}: {term.translation}")

        return "\n".join(addon_parts)


class SmartTermMatcher:
    """智能术语匹配器 - 处理术语边界和上下文"""

    def __init__(self):
        self._boundary_chars = set(" \t\n\r.,;:!?()[]{}\"'`/\\|@#$%^&*~-_+=<>")

    def is_word_boundary(self, text: str, start: int, end: int) -> bool:
        """检查匹配位置是否是词边界"""
        if start > 0:
            prev_char = text[start - 1]
            if prev_char not in self._boundary_chars and not prev_char.isalnum():
                # 如果前一个字符是字母或数字，检查是否是单词的一部分
                if prev_char.isalpha() or prev_char.isdigit():
                    return False

        if end < len(text):
            next_char = text[end]
            if next_char not in self._boundary_chars and not next_char.isalnum():
                if next_char.isalpha() or next_char.isdigit():
                    return False

        return True

    def find_terms_in_text(self, text: str, terms: list,
                           respect_boundary: bool = True) -> list:
        """
        在文本中查找术语（支持词边界检查）

        Args:
            text: 要搜索的文本
            terms: 术语列表
            respect_boundary: 是否检查词边界

        Returns:
            找到的术语列表 [(entry, start, end), ...]
        """
        found = []

        for entry in terms:
            term = entry.term
            if not term:
                continue

            # 构建正则
            pattern = re.escape(term)
            if not entry.case_sensitive:
                flags = re.IGNORECASE
            else:
                flags = 0

            if respect_boundary:
                # 添加词边界
                pattern = r'\b' + pattern + r'\b'

            for match in re.finditer(pattern, text, flags):
                found.append((entry, match.start(), match.end()))

        # 按位置排序
        found.sort(key=lambda x: x[1])

        # 去除重叠
        non_overlapping = []
        last_end = -1
        for entry, start, end in found:
            if start >= last_end:
                non_overlapping.append((entry, start, end))
                last_end = end

        return non_overlapping


def create_default_replacer() -> TermReplacer:
    """创建默认术语替换器"""
    return TermReplacer()


def create_smart_matcher() -> SmartTermMatcher:
    """创建智能匹配器"""
    return SmartTermMatcher()