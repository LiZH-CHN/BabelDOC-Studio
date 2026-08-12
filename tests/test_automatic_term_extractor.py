"""单元测试 - automatic_term_extractor.py 的 JSON 解析和术语提取"""

import json
import pytest
from babeldoc.format.pdf.document_il.midend.automatic_term_extractor import (
    AutomaticTermExtractor,
)


class TestCleanJsonOutput:
    """测试 _clean_json_output 清洗方法"""

    def test_strip_json_tags(self):
        output = "<json>[{\"src\": \"a\", \"tgt\": \"b\"}]</json>"
        result = AutomaticTermExtractor._clean_json_output(output)
        assert not result.startswith("<json>")
        assert not result.endswith("</json>")

    def test_strip_markdown_code_block(self):
        output = "```json\n[{\"src\": \"a\", \"tgt\": \"b\"}]\n```"
        result = AutomaticTermExtractor._clean_json_output(output)
        assert not result.startswith("```")
        assert not result.endswith("```")

    def test_extract_json_from_mixed_text(self):
        """从混合文本中找到 JSON 起始位置"""
        output = "Some analysis text here.\n[{\"src\": \"a\", \"tgt\": \"b\"}]"
        result = AutomaticTermExtractor._clean_json_output(output)
        assert result.startswith("[")

    def test_no_json_returns_original(self):
        output = "This is just text without any JSON"
        result = AutomaticTermExtractor._clean_json_output(output)
        assert result == output.strip()


class TestRobustJsonDecode:
    """测试 _robust_json_decode 鲁棒 JSON 解析"""

    def test_parse_standard_array(self):
        text = '[{"src": "LLM", "tgt": "大语言模型"}, {"src": "GPT", "tgt": "GPT"}]'
        result = AutomaticTermExtractor._robust_json_decode(text)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["src"] == "LLM"

    def test_parse_concatenated_objects(self):
        """解析 {obj1}{obj2} 拼接格式"""
        text = '{"src": "LLM", "tgt": "大语言模型"}{"src": "GPT", "tgt": "GPT"}'
        result = AutomaticTermExtractor._robust_json_decode(text)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["src"] == "LLM"
        assert result[1]["src"] == "GPT"

    def test_parse_single_object(self):
        text = '{"src": "LLM", "tgt": "大语言模型"}'
        result = AutomaticTermExtractor._robust_json_decode(text)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_parse_mixed_natural_text_and_json(self):
        """从自然语言中跳过非 JSON 文本，找到并解析 JSON"""
        text = """The user wants to extract key terms from the provided text.

Let me analyze:
- "PIV" is an acronym
- "propeller" is...

OK here's the output:
{"src": "PIV", "tgt": "PIV"}{"src": "propeller", "tgt": "螺旋桨"}"""
        result = AutomaticTermExtractor._robust_json_decode(text)
        assert result is not None
        assert len(result) >= 1

    def test_parse_empty_array(self):
        text = "[]"
        result = AutomaticTermExtractor._robust_json_decode(text)
        assert result == []

    def test_no_valid_json(self):
        text = "This is just natural language text with no JSON at all."
        result = AutomaticTermExtractor._robust_json_decode(text)
        assert result is None


class TestExtractTermsFromNaturalLanguage:
    """测试 _extract_terms_from_natural_language"""

    def test_extract_arrow_pattern(self):
        text = '- "PIV" -> "粒子图像测速"\n- "propeller" -> "螺旋桨"'
        result = AutomaticTermExtractor._extract_terms_from_natural_language(text)
        assert result is not None
        assert len(result) == 2
        assert result[0]["src"] == "PIV"
        assert result[0]["tgt"] == "粒子图像测速"

    def test_extract_json_fragments(self):
        text = '{"src": "LLM", "tgt": "大语言模型"}{"src": "GPT", "tgt": "GPT"}'
        result = AutomaticTermExtractor._extract_terms_from_natural_language(text)
        assert result is not None
        assert len(result) >= 1

    def test_no_terms_found(self):
        text = "This is just analysis. No terms here."
        result = AutomaticTermExtractor._extract_terms_from_natural_language(text)
        assert result is None

    def test_filter_same_src_tgt(self):
        """src == tgt 的条目被过滤，返回 None"""
        text = '"test" -> "test"'
        result = AutomaticTermExtractor._extract_terms_from_natural_language(text)
        # src == tgt 被过滤，无有效条目
        assert result is None