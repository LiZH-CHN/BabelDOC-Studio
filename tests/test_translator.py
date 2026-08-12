"""单元测试 - translator.py 的 _extract_translation_from_output 和推理链清洗"""

import pytest
from babeldoc.translator.translator import OpenAITranslator


class TestExtractTranslationFromOutput:
    """测试从推理链/自然语言中提取纯译文"""

    def test_normal_short_text_passes_through(self):
        """短文本不触发提取"""
        text = "模型试验是探索船用螺旋桨尾流动力学的可靠方法"
        result = OpenAITranslator._extract_translation_from_output(text, "original")
        assert result == text

    def test_extract_translation_from_chain_of_thought(self):
        """从推理链中提取 Translation: 后的内容"""
        output = """1. **Analyze the Request:**
* Role: Professional zh native translator.
* Goal: Translate text into zh fluently.
2. **Input text analysis:**
PIV tests are conducted at J = 0.5...
3. **Translate Segment by Segment:**
* Translation: 模型试验是探索船用螺旋桨尾流动力学的可靠方法
4. **Review and Refine:**
* Check tags: All preserved."""
        result = OpenAITranslator._extract_translation_from_output(output, "original")
        assert result == "模型试验是探索船用螺旋桨尾流动力学的可靠方法"

    def test_extract_last_translation(self):
        """多行 Translation 时取最后一个"""
        output = """1. **Analyze**:
* Translation: 第一句翻译
* Translation: 第二句翻译
* Translation: 最后一句翻译"""
        result = OpenAITranslator._extract_translation_from_output(output, "original")
        assert result == "最后一句翻译"

    def test_normal_multiline_passes_through(self):
        """正常多行翻译输出不触发提取，完整返回"""
        output = """群体智能在自然界中表现尤为明显。
它广泛应用于复杂系统建模与控制。
例如群体行为建模和优化算法等。
许多研究者对此进行了深入探讨。"""
        result = OpenAITranslator._extract_translation_from_output(output, "original")
        assert result == output

    def test_no_translation_fallback_to_original(self):
        """含中文推理文本时优先返回中文内容，不回退到英文原文"""
        output = """1. **Analyze**: 分析请求需要理解上下文
2. **Role**: 专业翻译人员
3. **Task**: 将英文科技文本翻译为流畅的简体中文
4. 需要保持标签和占位符不变
5. Seg 1"""
        result = OpenAITranslator._extract_translation_from_output(output, "original")
        # 新行为：含中文时返回中文内容（优于保留英文原文）
        assert "\u4e00" <= result[0] <= "\u9fff"
        assert result != "original"

    def test_extract_from_arrow_format(self):
        """从箭头格式的推理链中提取中文译文"""
        output = """1. **Analyze the Request:**
* Role: Professional zh native translator.
2. **Translate:**
"Assoc. Prof. Mustafa Ozguven is an accomplished" -> 穆斯塔法·奥兹古文副教授是一位杰出的
"entrepreneur with a Ph.D. in Management." -> 企业家，拥有管理学博士学位。
3. **Review:** check consistency."""
        result = OpenAITranslator._extract_translation_from_output(output, "original")
        assert result == "穆斯塔法·奥兹古文副教授是一位杰出的企业家，拥有管理学博士学位。"

    def test_arrow_filter_reasoning_commentary(self):
        """箭头提取过滤掉推理旁白（Wait, Let's, Actually 等）"""
        output = """3. **Translate the Human-Readable Text:** *
"Assoc. Prof. Mustafa Ozguven is an accomplished" -> 穆斯塔法·奥兹古文副教授是一位杰出的
"entrepreneur with a Ph.D. in Management." -> 企业家，拥有管理学博士学位。
(Wait, "United" is cut off. Let's translate just "founded" -> 在美国创办了 - wait,)
"founded multinational companies in the United States." -> 在美国创办了跨国企业。"""
        result = OpenAITranslator._extract_translation_from_output(output, "original")
        assert "Wait" not in result
        assert "Let's" not in result
        assert "穆斯塔法·奥兹古文副教授" in result
        assert "在美国创办了跨国企业" in result

    def test_deep_reasoning_with_embedded_arrows(self):
        """推理深度嵌入括号和行内注释的情况"""
        output = """1. **Analyze the Request:**
* Role: Professional zh native translator.
2. **Input text analysis:**
Assoc. Prof. Mustafa Ozguven is an accomplished entrepreneur with a Ph.D. in Management.
3. **Translate the Human-Readable Text:**
"Assoc. Prof. Mustafa Ozguven is an accomplished" -> 穆斯塔法·奥兹古文副教授是一位杰出的
"entrepreneur with a Ph.D. in Management. He has" -> 企业家，拥有管理学博士学位。他
"founded multinational companies in the United" -> 在美国、中国和土耳其创办了跨国企业。
(Wait, "United" is cut off. Let's translate "founded multinational companies in the United States, China, and Turkey." -> 在美国、中国和土耳其创办了跨国企业。)
4. **Review and Refine:** check consistency."""
        result = OpenAITranslator._extract_translation_from_output(output, "original")
        assert "Wait" not in result
        assert "Let's" not in result
        assert "穆斯塔法·奥兹古文副教授" in result
        assert "企业家，拥有管理学博士学位" in result

    def test_short_output_no_extraction(self):
        """短输出（<200字符）直接返回原文"""
        output = "Short translation here"
        result = OpenAITranslator._extract_translation_from_output(output, "original")
        assert result == output

    def test_step3_no_overdelete_reasoning_inline(self):
        """步骤3不应删除整行：关键词+3词后保留同行的翻译内容"""
        output = """1. **Analyze**: Review the text.
2. **Translate**:
Wait, actually the original text needs adjustment before translating.
第一段翻译内容在这里
Actually, let's check the second part more carefully too.
第二段翻译内容在这里
3. **Review**: Check consistency."""
        result = OpenAITranslator._extract_translation_from_output(output, "original")
        assert "第一段翻译内容在这里" in result
        assert "第二段翻译内容在这里" in result
        # 不应返回推理碎片
        assert "Review" not in result
        assert len(result) > 10

    def test_reasoning_keywords_in_middle_of_lines_preserved(self):
        """步骤3仅删除关键词+3词，不删除整行——翻译内容应保留"""
        output = """1. **Analyze**: Understand the text.
2. **Translate**: 
The software actually provides three main features for users.
-> 该软件实际上为用户提供三个主要功能。
The system also supports real-time monitoring.
-> 该系统还支持实时监控。
3. **Review**."""
        result = OpenAITranslator._extract_translation_from_output(output, "original")
        assert "该软件" in result
        assert "该系统还支持实时监控" in result
        assert "Review" not in result

    def test_v2_deep_reasoning_no_tags(self):
        """深度推理+无明确翻译标记：至少提取到有意义的中文内容，不返回空白或推理碎片"""
        output = """1. **Analyze**: 文本是关于数据科学的介绍。
2. **Role**: 专业翻译人员，需准确传达技术术语。
3. **Task**: 将英文内容翻译为简体中文。

Wait, let's reconsider the terminology. Actually, "data pipeline" is better translated as 数据管道 in this context.
Hmm, but wait, the original text uses "data processing pipeline" which is slightly different.
Or just use 数据处理管道 for clarity. Stick closer to the original meaning.

数据科学是一门利用数据提取知识和洞察的学科。
它涉及数据收集、清洗、分析和可视化的完整流程。
现代数据科学依赖于机器学习和统计方法。

4. **Review**: Check the translation quality and consistency."""
        result = OpenAITranslator._extract_translation_from_output(output, "original")
        # 方法6（最长中文段）在无标记时返回最长中文块——至少不是空白/推理碎片
        assert "\u4e00" <= result[0] <= "\u9fff"  # 以中文开头
        assert len(result) > 10
        assert "Review" not in result
        assert "terminology" not in result
        assert result != "original"  # 不应回退到原文

    def test_v2_pure_chinese_translation_no_trigger(self):
        """纯中文翻译输出不触发CoT检测，完整保留"""
        output = """深度学习是机器学习的一个分支。
它使用多层神经网络来学习数据的层次化表示。
卷积神经网络在图像识别任务中表现优异。
循环神经网络适合处理序列数据。"""
        result = OpenAITranslator._extract_translation_from_output(output, "original")
        assert result == output

    def test_v3_inline_chinese_extraction(self):
        """方法6不限行首：内联在同一行的中文翻译也能提取"""
        output = """1. **Analyze**: This text discusses machine learning concepts. 2. **Translate**: 机器学习是一种人工智能技术，它使计算机能够从数据中学习。 3. **Review**: The translation is accurate."""
        result = OpenAITranslator._extract_translation_from_output(output, "original English text")
        assert "机器学习" in result
        assert "人工智能技术" in result
        assert result != "original English text"

    def test_v3_fallback_returns_chinese_not_english(self):
        """所有提取方法失败时，如果清理后文本含中文则返回中文，不回退到英文原文"""
        output = """1. **Analyze**: Understanding the context.
2. **Task**: Translate to Chinese.
The concept of 数据科学 involves extracting insights from data.
3. **Review**: Check accuracy."""
        result = OpenAITranslator._extract_translation_from_output(output, "original English text about data science")
        assert "\u4e00" <= result[0] <= "\u9fff" or "数据科学" in result
        assert result != "original English text about data science"

    def test_v3_short_chinese_extraction(self):
        """方法7：较短中文段（≥3字符）也能被提取"""
        output = """1. **Analyze**: Short text.
2. **Translate**: 数据科学
3. **Review**: Done."""
        result = OpenAITranslator._extract_translation_from_output(output, "data science")
        assert "数据科学" in result
        assert result != "data science"