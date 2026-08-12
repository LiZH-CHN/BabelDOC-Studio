"""
QA 检查与质量评分模块
提供翻译质量检查、评分和报告功能
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class Severity(Enum):
    """问题严重程度"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class QAIssue:
    """QA 检查发现的问题"""
    rule_name: str
    severity: Severity
    message: str
    source_text: str = ""
    target_text: str = ""
    position: int = 0
    suggestion: str = ""


@dataclass
class QualityScore:
    """质量评分结果"""
    overall: float = 0.0  # 总分 0-100
    accuracy: float = 0.0  # 准确性
    fluency: float = 0.0  # 流畅性
    consistency: float = 0.0  # 一致性
    terminology: float = 0.0  # 术语一致性
    completeness: float = 0.0  # 完整性
    issues: list = field(default_factory=list)

    def grade(self) -> str:
        """获取质量等级"""
        if self.overall >= 90:
            return "A (优秀)"
        elif self.overall >= 80:
            return "B (良好)"
        elif self.overall >= 70:
            return "C (合格)"
        elif self.overall >= 60:
            return "D (待改进)"
        else:
            return "F (不合格)"


class QAChecker:
    """翻译质量检查器"""

    def __init__(self):
        self.rules = []
        self._register_default_rules()

    def _register_default_rules(self):
        """注册默认检查规则"""
        self.rules = [
            self._check_empty_translation,
            self._check_length_ratio,
            self._check_numbers_consistency,
            self._check_punctuation_consistency,
            self._check_html_tags_consistency,
            self._check_repeated_words,
            self._check_untranslated_segments,
            self._check_leading_trailing_spaces,
        ]

    def add_rule(self, rule_func):
        """添加自定义检查规则"""
        self.rules.append(rule_func)

    def check(self, source: str, target: str,
              glossary_terms: list = None) -> list:
        """
        执行 QA 检查

        Args:
            source: 源文本
            target: 译文
            glossary_terms: 术语库条目列表

        Returns:
            问题列表
        """
        issues = []
        context = {
            "source": source,
            "target": target,
            "glossary": glossary_terms or [],
        }

        for rule in self.rules:
            try:
                rule_issues = rule(context)
                if rule_issues:
                    issues.extend(rule_issues)
            except Exception:
                pass

        return issues

    # ============================================================
    # 内置检查规则
    # ============================================================

    def _check_empty_translation(self, context: dict) -> list:
        """检查空翻译"""
        issues = []
        source = context["source"].strip()
        target = context["target"].strip()

        if source and not target:
            issues.append(QAIssue(
                rule_name="空翻译",
                severity=Severity.CRITICAL,
                message="源文本有内容但译文为空",
                source_text=source,
                target_text=target,
                suggestion="请提供翻译",
            ))
        elif not source and target:
            issues.append(QAIssue(
                rule_name="多余翻译",
                severity=Severity.WARNING,
                message="源文本为空但有译文",
                source_text=source,
                target_text=target,
            ))

        return issues

    def _check_length_ratio(self, context: dict) -> list:
        """检查长度比例（异常长度可能表示翻译问题）"""
        issues = []
        source = context["source"].strip()
        target = context["target"].strip()

        if not source or not target:
            return issues

        source_len = len(source)
        target_len = len(target)

        # 译文为空的情况已在空翻译检查中处理
        if target_len == 0:
            return issues

        ratio = target_len / source_len if source_len > 0 else 0

        # 中文翻译通常比英文短
        if ratio > 3.0:
            issues.append(QAIssue(
                rule_name="译文过长",
                severity=Severity.WARNING,
                message=f"译文长度是源文的 {ratio:.1f} 倍，可能包含多余内容",
                source_text=source,
                target_text=target,
            ))
        elif ratio < 0.1 and source_len > 10:
            issues.append(QAIssue(
                rule_name="译文过短",
                severity=Severity.WARNING,
                message=f"译文长度仅为源文的 {ratio:.1%}，可能遗漏内容",
                source_text=source,
                target_text=target,
            ))

        return issues

    def _check_numbers_consistency(self, context: dict) -> list:
        """检查数字一致性"""
        issues = []
        source = context["source"]
        target = context["target"]

        # 提取源文中的数字
        source_numbers = set(re.findall(r'\d+(?:\.\d+)?', source))
        target_numbers = set(re.findall(r'\d+(?:\.\d+)?', target))

        # 检查是否有遗漏的数字
        missing = source_numbers - target_numbers
        if missing and source_numbers:
            issues.append(QAIssue(
                rule_name="数字不一致",
                severity=Severity.ERROR,
                message=f"译文中缺少数字: {', '.join(sorted(missing))}",
                source_text=source,
                target_text=target,
                suggestion=f"请确保数字 {', '.join(sorted(missing))} 在译文中正确出现",
            ))

        return issues

    def _check_punctuation_consistency(self, context: dict) -> list:
        """检查标点符号一致性"""
        issues = []
        source = context["source"]
        target = context["target"]

        # 检查引号匹配
        for quote_pair in [('"', '"'), ("'", "'"), ('「', '」'), ('“', '”')]:
            open_q, close_q = quote_pair
            src_open = source.count(open_q)
            src_close = source.count(close_q)
            tgt_open = target.count(open_q)
            tgt_close = target.count(close_q)

            if src_open != src_close and tgt_open == tgt_close and tgt_open > 0:
                issues.append(QAIssue(
                    rule_name="标点符号",
                    severity=Severity.INFO,
                    message=f"源文中 {open_q}{close_q} 不匹配，译文中已修正",
                    source_text=source,
                    target_text=target,
                ))

        # 检查句末标点
        source_stripped = source.rstrip()
        target_stripped = target.rstrip()
        if source_stripped and target_stripped:
            if source_stripped[-1] in '.。!！?？' and target_stripped[-1] not in '.。!！?？':
                issues.append(QAIssue(
                    rule_name="句末标点",
                    severity=Severity.WARNING,
                    message="源文有句末标点但译文缺少句末标点",
                    source_text=source,
                    target_text=target,
                ))

        return issues

    def _check_html_tags_consistency(self, context: dict) -> list:
        """检查 HTML/格式标签一致性"""
        issues = []
        source = context["source"]
        target = context["target"]

        # 提取标签
        source_tags = set(re.findall(r'<[^>]+>', source))
        target_tags = set(re.findall(r'<[^>]+>', target))

        missing_tags = source_tags - target_tags
        extra_tags = target_tags - source_tags

        if missing_tags:
            issues.append(QAIssue(
                rule_name="格式标签缺失",
                severity=Severity.ERROR,
                message=f"译文中缺少格式标签: {', '.join(sorted(missing_tags))}",
                source_text=source,
                target_text=target,
            ))

        if extra_tags:
            issues.append(QAIssue(
                rule_name="多余格式标签",
                severity=Severity.WARNING,
                message=f"译文中多出格式标签: {', '.join(sorted(extra_tags))}",
                source_text=source,
                target_text=target,
            ))

        return issues

    def _check_repeated_words(self, context: dict) -> list:
        """检查重复词（可能的翻译错误）"""
        issues = []
        target = context["target"]

        # 检查连续重复的词
        repeats = re.findall(r'(\b\w+)\s+\1\b', target, re.IGNORECASE)
        if repeats:
            issues.append(QAIssue(
                rule_name="重复词语",
                severity=Severity.WARNING,
                message=f"译文中出现重复词语: {', '.join(repeats)}",
                source_text=context["source"],
                target_text=target,
            ))

        return issues

    def _check_untranslated_segments(self, context: dict) -> list:
        """检查未翻译片段"""
        issues = []
        source = context["source"]
        target = context["target"]

        # 提取源文中的英文单词（如果目标语言是中文）
        source_words = re.findall(r'[a-zA-Z]{3,}', source)
        if not source_words:
            return issues

        # 检查是否有大量英文单词出现在译文中（可能未翻译）
        untranslated = [w for w in source_words if w in target]
        if len(untranslated) > len(source_words) * 0.5 and len(source_words) > 2:
            issues.append(QAIssue(
                rule_name="疑似未翻译",
                severity=Severity.WARNING,
                message=f"译文中保留了 {len(untranslated)}/{len(source_words)} 个英文单词",
                source_text=source,
                target_text=target,
                suggestion="请检查是否需要翻译这些术语或专有名词",
            ))

        return issues

    def _check_leading_trailing_spaces(self, context: dict) -> list:
        """检查首尾空格一致性"""
        issues = []
        source = context["source"]
        target = context["target"]

        if source and target:
            if (source[0] == ' ') != (target[0] == ' '):
                issues.append(QAIssue(
                    rule_name="前导空格",
                    severity=Severity.INFO,
                    message="源文和译文的前导空格不一致",
                    source_text=source,
                    target_text=target,
                ))
            if (source[-1] == ' ') != (target[-1] == ' '):
                issues.append(QAIssue(
                    rule_name="尾随空格",
                    severity=Severity.INFO,
                    message="源文和译文的尾随空格不一致",
                    source_text=source,
                    target_text=target,
                ))

        return issues


class QualityScorer:
    """翻译质量评分器"""

    def __init__(self):
        self.qa_checker = QAChecker()

    def score(self, source: str, target: str,
              tm_matches: list = None,
              glossary_terms: list = None) -> QualityScore:
        """
        对翻译进行质量评分

        Args:
            source: 源文本
            target: 译文
            tm_matches: 翻译记忆匹配结果
            glossary_terms: 术语库匹配结果

        Returns:
            QualityScore 对象
        """
        score = QualityScore()

        # 执行 QA 检查
        issues = self.qa_checker.check(source, target, glossary_terms)
        score.issues = issues

        # 计算完整性得分
        score.completeness = self._score_completeness(source, target, issues)

        # 计算一致性得分
        score.consistency = self._score_consistency(source, target, issues)

        # 计算术语得分
        score.terminology = self._score_terminology(source, target, glossary_terms, issues)

        # 计算流畅性得分（基于基本规则）
        score.fluency = self._score_fluency(target, issues)

        # 计算准确性得分（基于 QA 问题和 TM 匹配）
        score.accuracy = self._score_accuracy(source, target, tm_matches, issues)

        # 计算总分（加权平均）
        weights = {
            "accuracy": 0.35,
            "fluency": 0.20,
            "consistency": 0.20,
            "terminology": 0.15,
            "completeness": 0.10,
        }

        score.overall = (
            score.accuracy * weights["accuracy"] +
            score.fluency * weights["fluency"] +
            score.consistency * weights["consistency"] +
            score.terminology * weights["terminology"] +
            score.completeness * weights["completeness"]
        )

        # 确保分数在 0-100 范围内
        score.overall = max(0, min(100, score.overall))
        score.accuracy = max(0, min(100, score.accuracy))
        score.fluency = max(0, min(100, score.fluency))
        score.consistency = max(0, min(100, score.consistency))
        score.terminology = max(0, min(100, score.terminology))
        score.completeness = max(0, min(100, score.completeness))

        return score

    def _score_completeness(self, source: str, target: str, issues: list) -> float:
        """评分：完整性"""
        if not source.strip():
            return 100.0

        if not target.strip():
            return 0.0

        score = 100.0

        # 空翻译问题
        critical_issues = [i for i in issues if i.severity == Severity.CRITICAL]
        score -= len(critical_issues) * 50

        # 缺失数字
        for issue in issues:
            if issue.rule_name == "数字不一致":
                score -= 15

        return max(0, min(100, score))

    def _score_consistency(self, source: str, target: str, issues: list) -> float:
        """评分：一致性"""
        score = 100.0

        for issue in issues:
            if issue.severity == Severity.ERROR:
                score -= 20
            elif issue.severity == Severity.WARNING:
                score -= 10
            elif issue.severity == Severity.INFO:
                score -= 2

        return max(0, min(100, score))

    def _score_terminology(self, source: str, target: str,
                           glossary_terms: list, issues: list) -> float:
        """评分：术语一致性"""
        if not glossary_terms:
            return 85.0  # 无术语库时给默认分

        score = 100.0
        matched_terms = 0

        for term in glossary_terms:
            if term.case_sensitive:
                if term.term in source and term.translation in target:
                    matched_terms += 1
            else:
                if term.term.lower() in source.lower() and term.translation.lower() in target.lower():
                    matched_terms += 1

        if glossary_terms:
            match_rate = matched_terms / len(glossary_terms)
            score = 60 + 40 * match_rate

        return max(0, min(100, score))

    def _score_fluency(self, target: str, issues: list) -> float:
        """评分：流畅性"""
        if not target.strip():
            return 0.0

        score = 100.0

        for issue in issues:
            if issue.rule_name == "重复词语":
                score -= 15
            elif issue.rule_name == "译文过长" or issue.rule_name == "译文过短":
                score -= 10

        return max(0, min(100, score))

    def _score_accuracy(self, source: str, target: str,
                        tm_matches: list, issues: list) -> float:
        """评分：准确性"""
        score = 100.0

        # TM 匹配加分
        if tm_matches:
            best_match = max(tm_matches, key=lambda x: x[1])
            if best_match[1] > 0.9:
                score = 95.0
            elif best_match[1] > 0.8:
                score = 85.0
            elif best_match[1] > 0.7:
                score = 75.0
            else:
                score = 65.0

        # 严重问题扣分
        for issue in issues:
            if issue.severity == Severity.CRITICAL:
                score -= 40
            elif issue.severity == Severity.ERROR:
                score -= 15
            elif issue.severity == Severity.WARNING:
                score -= 5

        return max(0, min(100, score))

    def batch_score(self, segments: list) -> dict:
        """
        批量评分

        Args:
            segments: [(source, target), ...] 列表

        Returns:
            包含总分和详细评分的字典
        """
        scores = []
        total_issues = []

        for source, target in segments:
            score = self.score(source, target)
            scores.append(score)
            total_issues.extend(score.issues)

        if not scores:
            return {"overall": 0, "count": 0}

        avg_score = QualityScore(
            overall=sum(s.overall for s in scores) / len(scores),
            accuracy=sum(s.accuracy for s in scores) / len(scores),
            fluency=sum(s.fluency for s in scores) / len(scores),
            consistency=sum(s.consistency for s in scores) / len(scores),
            terminology=sum(s.terminology for s in scores) / len(scores),
            completeness=sum(s.completeness for s in scores) / len(scores),
            issues=total_issues,
        )

        return {
            "overall": avg_score.overall,
            "accuracy": avg_score.accuracy,
            "fluency": avg_score.fluency,
            "consistency": avg_score.consistency,
            "terminology": avg_score.terminology,
            "completeness": avg_score.completeness,
            "grade": avg_score.grade(),
            "total_segments": len(segments),
            "total_issues": len(total_issues),
            "issues_by_severity": {
                "critical": len([i for i in total_issues if i.severity == Severity.CRITICAL]),
                "error": len([i for i in total_issues if i.severity == Severity.ERROR]),
                "warning": len([i for i in total_issues if i.severity == Severity.WARNING]),
                "info": len([i for i in total_issues if i.severity == Severity.INFO]),
            },
        }