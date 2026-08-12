"""单元测试 - il_translator_llm_only.py 的 JSON 解析"""

import pytest
from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (
    ILTranslatorLLMOnly,
)


class TestIlTranslatorRobustJsonDecode:
    """测试 il_translator 的 _robust_json_decode"""

    def test_parse_concatenated_objects_with_skip(self):
        """解析跳过非 JSON 文本的 {obj1}{obj2}"""
        text = '''Prompt analysis text...
Let me output:
{"id": 0, "output": "你好", "input": "hello"}{"id": 1, "output": "世界", "input": "world"}'''
        result = ILTranslatorLLMOnly._robust_json_decode(text)
        assert result is not None
        assert len(result) >= 2

    def test_parse_standard_array(self):
        text = '[{"id": 0, "output": "你好"}, {"id": 1, "output": "世界"}]'
        result = ILTranslatorLLMOnly._robust_json_decode(text)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_parse_single_object(self):
        text = '{"id": 0, "output": "你好"}'
        result = ILTranslatorLLMOnly._robust_json_decode(text)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_no_valid_json(self):
        text = "This has no JSON at all"
        result = ILTranslatorLLMOnly._robust_json_decode(text)
        assert result is None


class TestIlTranslatorCleanJsonOutput:
    """测试 il_translator 的 _clean_json_output"""

    def test_strip_markdown(self):
        output = '```json\n[{"id": 0, "output": "test"}]\n```'
        result = ILTranslatorLLMOnly._clean_json_output(output)
        assert not result.startswith("```")

    def test_strip_prefix_text(self):
        """从自然语言前缀中提取 JSON"""
        output = 'Chain of thought analysis...\nHere is the result:\n[{"id": 0, "output": "test"}]'
        result = ILTranslatorLLMOnly._clean_json_output(output)
        assert result.startswith("[")