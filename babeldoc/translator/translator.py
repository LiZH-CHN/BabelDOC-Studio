import certifi
import contextlib
import logging
import os
import re
import ssl
import sys
import threading
import time
import unicodedata
from abc import ABC
from abc import abstractmethod
from typing import Any, Optional

import httpx
import openai
from tenacity import before_sleep_log
from tenacity import retry
from tenacity import retry_if_exception
from tenacity import stop_after_attempt
from tenacity import wait_exponential

from babeldoc.babeldoc_exception.BabelDOCException import ContentFilterError
from babeldoc.translator.cache import TranslationCache
from babeldoc.translator.model_limits import (
    DEFAULT_TEXT_MIN_TOKENS,
    MAX_OUTPUT_TOKENS_CAP,
    MIN_OUTPUT_TOKENS,
    compute_output_token_budget,
    get_model_limits,
)
from babeldoc.utils.atomic_integer import AtomicInteger

logger = logging.getLogger(__name__)


def remove_control_characters(s: str) -> str:
    """移除字符串中的控制字符。

    Args:
        s: 输入字符串

    Returns:
        移除控制字符后的字符串
    """
    return "".join(ch for ch in s if unicodedata.category(ch)[0] != "C")


def _is_retryable_network_error(exception: Exception) -> bool:
    """判断是否为可重试的网络错误（断网、超时、连接失败等）

    Args:
        exception: 异常对象

    Returns:
        是否为可重试的网络错误
    """
    return isinstance(
        exception,
        (openai.APIConnectionError, openai.APITimeoutError),
    )


def _is_retryable_error(exception: Exception) -> bool:
    """判断是否为可重试的错误（限流 + 网络错误）

    Args:
        exception: 异常对象

    Returns:
        是否为可重试的错误
    """
    return isinstance(exception, openai.RateLimitError) or _is_retryable_network_error(exception)


def _custom_wait(retry_state: Any) -> float:
    """根据异常类型自定义退避等待时间。

    限流错误使用较短退避（1-15s），网络错误使用较长退避（5-60s）。

    Args:
        retry_state: tenacity 重试状态对象

    Returns:
        等待时间（秒）
    """
    exc = retry_state.outcome.exception()
    if isinstance(exc, openai.RateLimitError):
        # 限流：指数退避 1-15s
        return wait_exponential(multiplier=1, min=1, max=15)(retry_state)
    else:
        # 网络错误：更长退避 5-60s
        return wait_exponential(multiplier=2, min=5, max=60)(retry_state)


class RateLimiter:
    """
    A rate limiter using the leaky bucket algorithm to ensure a smooth, constant rate of requests.
    This implementation is thread-safe and robust against system clock changes.
    """

    def __init__(self, max_qps: int):
        if max_qps <= 0:
            raise ValueError("max_qps must be a positive number")
        self.max_qps = max_qps
        self.min_interval = 1.0 / max_qps
        self.lock = threading.Lock()
        # Use monotonic time to prevent issues with system time changes
        self.next_request_time = time.monotonic()

    def wait(self, _rate_limit_params: dict = None):
        """
        Blocks until the next request can be processed, ensuring the rate limit is not exceeded.
        修复：将 sleep 移到锁外，避免持有锁睡眠导致所有线程串行阻塞。
        """
        # 第一步：在锁内计算需要等待的时间（快速操作）
        with self.lock:
            now = time.monotonic()
            wait_duration = self.next_request_time - now
            if wait_duration > 0:
                self.next_request_time = self.next_request_time + self.min_interval
            else:
                now = time.monotonic()
                self.next_request_time = max(self.next_request_time, now) + self.min_interval
                wait_duration = 0

        # 第二步：在锁外睡眠，不阻塞其他线程
        if wait_duration > 0:
            time.sleep(wait_duration)

    def set_max_qps(self, max_qps: int):
        """
        Updates the maximum queries per second. This operation is thread-safe.
        """
        if max_qps <= 0:
            raise ValueError("max_qps must be a positive number")
        with self.lock:
            self.max_qps = max_qps
            self.min_interval = 1.0 / max_qps


_translate_rate_limiter = RateLimiter(5)


def set_translate_rate_limiter(max_qps):
    _translate_rate_limiter.set_max_qps(max_qps)


def _create_ssl_context():
    """创建SSL上下文，兼容PyInstaller打包环境"""
    if getattr(sys, 'frozen', False):
        # 打包后：使用 sys._MEIPASS 获取证书路径
        cert_path = os.path.join(sys._MEIPASS, "certifi", "cacert.pem")
    else:
        # 打包前：使用 certifi.where()
        cert_path = certifi.where()
    return ssl.create_default_context(cafile=cert_path)

# 未配置上下文长度时的默认回退值（128K）。
DEFAULT_CONTEXT_LENGTH = 128 * 1024


def _normalize_context_length(context_length) -> int:
    """将上下文长度规整为 int；非法/缺失值回退默认。"""
    if isinstance(context_length, int) and not isinstance(context_length, bool):
        return context_length
    return DEFAULT_CONTEXT_LENGTH


def compute_batch_token_limit(context_length: int | None) -> int:
    """按模型上下文长度分级计算批处理（JSON 批量翻译）的输入 token 上限。"""
    ctx = _normalize_context_length(context_length)
    if ctx <= 32 * 1024:
        return 200
    if ctx <= 128 * 1024:
        return 500
    return 1000


def parse_context_length(context: str | None) -> int | None:
    """将 "8K"/"64K"/"1M"/"10M" 等上下文长度字符串解析为 token 数。"""
    if not context:
        return None
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([kKmM])$", context.strip())
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "k":
        return int(value * 1024)
    if unit == "m":
        return int(value * 1024 * 1024)
    return None


class BaseTranslator(ABC):
    # Due to cache limitations, name should be within 20 characters.
    # cache.py: translate_engine = CharField(max_length=20)
    name = "base"
    lang_map = {}

    def __init__(self, lang_in, lang_out, ignore_cache):
        self.ignore_cache = ignore_cache
        lang_in = self.lang_map.get(lang_in.lower(), lang_in)
        lang_out = self.lang_map.get(lang_out.lower(), lang_out)
        self.lang_in = lang_in
        self.lang_out = lang_out

        self.cache = TranslationCache(
            self.name,
            {
                "lang_in": lang_in,
                "lang_out": lang_out,
            },
        )

        self.translate_call_count = 0
        self.translate_cache_call_count = 0

    def __del__(self):
        with contextlib.suppress(Exception):
            logger.info(
                f"{self.name} translate call count: {self.translate_call_count}"
            )
            logger.info(
                f"{self.name} translate cache call count: {self.translate_cache_call_count}",
            )

    def add_cache_impact_parameters(self, k: str, v):
        """
        Add parameters that affect the translation quality to distinguish the translation effects under different parameters.
        :param k: key
        :param v: value
        """
        self.cache.add_params(k, v)

    def translate(self, text, ignore_cache=False, rate_limit_params: dict = None):
        """
        Translate the text, and the other part should call this method.
        :param text: text to translate
        :return: translated text
        """
        self.translate_call_count += 1
        if not (self.ignore_cache or ignore_cache):
            try:
                cache = self.cache.get(text)
                if cache is not None:
                    self.translate_cache_call_count += 1
                    return cache
            except Exception as e:
                logger.debug(f"try get cache failed, ignore it: {e}")
        _translate_rate_limiter.wait()
        translation = self.do_translate(text, rate_limit_params)
        if translation is None:
            logger.warning("do_translate returned None, using original text as fallback")
            translation = text
        if not (self.ignore_cache or ignore_cache):
            self.cache.set(text, translation)
        return translation

    def llm_translate(self, text, ignore_cache=False, rate_limit_params: dict = None):
        """
        Translate the text, and the other part should call this method.
        :param text: text to translate
        :return: translated text
        """
        self.translate_call_count += 1
        if not (self.ignore_cache or ignore_cache):
            try:
                cache = self.cache.get(text)
                if cache is not None:
                    self.translate_cache_call_count += 1
                    return cache
            except Exception as e:
                logger.debug(f"try get cache failed, ignore it: {e}")
        _translate_rate_limiter.wait()
        translation = self.do_llm_translate(text, rate_limit_params)
        if translation is None:
            logger.warning("do_llm_translate returned None, using original text as fallback")
            translation = text
        if not (self.ignore_cache or ignore_cache):
            try:
                self.cache.set(text, translation)
            except Exception as e:
                logger.debug(
                    f"try set cache failed, ignore it: {e}, text: {text}, translation: {translation}"
                )
        return translation

    @abstractmethod
    def do_llm_translate(self, text, rate_limit_params: dict = None):
        """
        Actual translate text, override this method
        :param text: text to translate
        :return: translated text
        """
        raise NotImplementedError

    @abstractmethod
    def do_translate(self, text, rate_limit_params: dict = None):
        """
        Actual translate text, override this method
        :param text: text to translate
        :return: translated text
        """
        logger.critical(
            f"Do not call BaseTranslator.do_translate. "
            f"Translator: {self}. "
            f"Text: {text}. ",
        )
        raise NotImplementedError

    def __str__(self):
        return f"{self.name} {self.lang_in} {self.lang_out} {self.model}"

    def get_rich_text_left_placeholder(self, placeholder_id: int | str):
        return f"<b{placeholder_id}>"

    def get_rich_text_right_placeholder(self, placeholder_id: int | str):
        return f"</b{placeholder_id}>"

    def get_formular_placeholder(self, placeholder_id: int | str):
        return self.get_rich_text_left_placeholder(placeholder_id)


# ============================================================
# 译文提取辅助函数（从推理链中提取纯译文）
# ============================================================

# 推理链特征正则模式
_COT_PATTERNS = [
    r'(?:^|\n)\s*\d+\.\s*\*\*',
    r'(?:^|\n)\s*\d+\.\s*Analyze',
    r'(?:^|\n)\s*\d+\.\s*[Rr]ole\b',
    r'(?:^|\n)\s*\d+\.\s*[Ii]nput\b',
    r'(?:^|\n)\s*\d+\.\s*[Gg]oal\b',
    r'(?:^|\n)\s*\d+\.\s*[Tt]ask\b',
    r'(?:^|\n)\s*\d+\.\s*[Rr]eview\b',
    r'(?:^|\n)\s*\d+\.\s*[Tt]ranslate\b',
    r'(?:^|\n)\s*(?:分析|角色|任务|目标|输入|审查|最终输出)',
]

# 推理关键词
_REASONING_KEYWORDS = r'\b(?:wait|let[\'\u2019]s|actually|hmm|but\s+wait|or\s+just|stick\s+closer)\b'
_REASONING_KEYWORDS_EXTENDED = r'\b(?:wait|let[\'\u2019]s|actually|hmm|but\s+wait|or\s+just|stick\s+closer|analysis|analyze|role|review)\b'


def _is_chain_of_thought(output: str) -> bool:
    """检测输出是否包含推理链特征"""
    return any(re.search(p, output) for p in _COT_PATTERNS)


def _clean_output(output: str) -> str:
    """移除推理旁白（括号内内容、行内注释）"""
    # 步骤1：移除所有括号及括号内的内容
    cleaned = re.sub(r'\s*\([^)]*\)', '', output)
    # 步骤2：移除行内推理注释
    cleaned = re.sub(r'\s*[-—–]\s*(?:wait|let[\'\u2019]s|actually|hmm|but\s+wait).*', '', cleaned, flags=re.IGNORECASE)
    # 步骤3：仅移除推理关键词及其后最多3个词
    cleaned = re.sub(r'\b(?:wait|let[\'\u2019]s|actually|hmm|but\s+wait|or\s+just|stick\s+closer)[\s,.]*(?:\S+\s*){0,3}', '', cleaned, flags=re.IGNORECASE)
    return cleaned


def _extract_by_translation_marker(cleaned: str) -> str | None:
    """方法1：匹配 'Translation:' 行后的内容"""
    matches = re.findall(
        r'(?:^|\n)\s*\*?\s*Translation\s*:?\s*(.+)',
        cleaned, re.MULTILINE | re.IGNORECASE,
    )
    if matches:
        return matches[-1].strip()
    return None


def _extract_translate_section(cleaned: str) -> str | None:
    """方法2：提取 'Translate' 章节中的纯中文行"""
    translate_section = re.search(
        r'(?:^|\n)\d+\.\s*\*{1,2}[Tt]ranslate.+?\*{1,2}[ \t]*\n?(.*?)(?:\n\s*\d+\.\s*\*|$)',
        cleaned, re.DOTALL,
    )
    if translate_section:
        section_text = translate_section.group(1).strip()
        cn_lines = re.findall(
            r'(?:^|\n)[ \t]*[\u4e00-\u9fff][^\n]{5,}',
            section_text, re.MULTILINE,
        )
        if cn_lines:
            combined = '\n'.join(l.strip() for l in cn_lines)
            if len(combined) > 10:
                return combined
    return None


def _extract_arrow_format(cleaned: str) -> str | None:
    """方法3：提取箭头格式译文"""
    arrow_matches = []
    for m in re.finditer(r'(?:->|→)\s*(.+?)(?:\s*\n|\s*$)', cleaned):
        target = m.group(1)
        if not re.search(r'[\u4e00-\u9fff]', target):
            continue
        if re.search(_REASONING_KEYWORDS, target, re.IGNORECASE):
            continue
        if len(target.strip()) < 3:
            continue
        arrow_matches.append(target.strip())
    if arrow_matches:
        combined = ''.join(arrow_matches)
        if len(combined) > 10:
            return combined
    return None


def _extract_by_cn_marker(cleaned: str) -> str | None:
    """方法4&5：提取含'翻译'/'译文'/'翻译结果'标记的段落"""
    # 方法4：提取含"翻译"/"译文"标记的段落
    cn_fallback = re.findall(
        r'(?:^|\n).*?(?:翻译|译文)[：:]\s*([\u4e00-\u9fff][^\n]{4,})',
        cleaned, re.MULTILINE,
    )
    if cn_fallback:
        candidate = cn_fallback[-1].strip()
        if len(candidate) > 5:
            return candidate

    # 方法5：提取包含"翻译结果"/"最终输出"标记的段落
    result_hint = re.search(
        r'(?:^|\n).*?(?:翻译结果|译文[：:]|最终输出|翻译[：:]\s*)([\u4e00-\u9fff][^\n]{4,})',
        cleaned, re.MULTILINE,
    )
    if result_hint:
        candidate = result_hint.group(1).strip()
        if len(candidate) > 5:
            return candidate
    return None


def _extract_longest_cn_block(cleaned: str) -> str | None:
    """方法6：提取最长的中文文本段"""
    cn_blocks = re.findall(
        r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef][^\n]{9,})',
        cleaned,
    )
    if cn_blocks:
        filtered = [b for b in cn_blocks if not re.search(_REASONING_KEYWORDS_EXTENDED, b, re.IGNORECASE)]
        if filtered:
            return max(filtered, key=len).strip()
        return max(cn_blocks, key=len).strip()
    return None


def _extract_all_cn_segments(cleaned: str) -> str | None:
    """方法7：提取所有中文连续段并合并"""
    all_cn = re.findall(
        r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]{2,}[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]?[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]*)',
        cleaned,
    )
    if all_cn:
        combined = ''.join(all_cn)
        if len(combined) >= 5:
            return combined.strip()
    return None


def _extract_translation_from_output(output: str, original_text: str) -> str:
    """从推理链/分析文本中提取纯译文的主函数

    当检测到推理链特征时，按优先级尝试多种提取方法。
    """
    if len(output) < 50:
        return output

    if not _is_chain_of_thought(output):
        return output

    cleaned = _clean_output(output)

    # 按优先级尝试各提取方法
    extractors = [
        _extract_by_translation_marker,
        _extract_translate_section,
        _extract_arrow_format,
        _extract_by_cn_marker,
        _extract_longest_cn_block,
        _extract_all_cn_segments,
    ]
    for extractor in extractors:
        result = extractor(cleaned)
        if result is not None:
            return result

    # 无法安全提取 → 如果清理后的文本包含中文，返回清理后文本；否则回退到原文本
    if re.search(r'[\u4e00-\u9fff]', cleaned) and len(cleaned.strip()) > 5:
        return cleaned.strip()
    return original_text


class OpenAITranslator(BaseTranslator):
    # https://github.com/openai/openai-python
    name = "openai"

    def __init__(
        self,
        lang_in,
        lang_out,
        model,
        base_url=None,
        api_key=None,
        ignore_cache=False,
        enable_json_mode_if_requested=False,
        send_dashscope_header=False,
        send_temperature=True,
        reasoning=None,
        thinking=None,
        context_length: int | None = None,
    ):
        super().__init__(lang_in, lang_out, ignore_cache)
        self.options = {"temperature": 0}  # 随机采样可能会打断公式标记
        self.extra_body = {}
        # if 'gpt-5' in model and 'gpt-5-chat' not in model:
        #     self.extra_body['reasoning'] = {
        #         "effort": "minimal"
        #     }
        #     self.add_cache_impact_parameters("reasoning-effort", 'minimal')

        self.reasoning = reasoning

        # 创建SSL上下文，兼容PyInstaller打包环境
        ssl_context = _create_ssl_context()

        self.client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key,
            http_client=httpx.Client(
                verify=ssl_context,
                limits=httpx.Limits(
                    max_connections=None, max_keepalive_connections=None
                ),
                timeout=httpx.Timeout(
                    connect=60.0,
                    read=1800.0,
                    write=60.0,
                    pool=60.0,
                ),
            ),
        )
        if send_temperature:
            self.add_cache_impact_parameters("temperature", self.options["temperature"])
        self.model = model
        self.enable_json_mode_if_requested = enable_json_mode_if_requested
        self.send_dashscope_header = send_dashscope_header
        self.send_temperature = send_temperature
        self.add_cache_impact_parameters("model", self.model)
        self.add_cache_impact_parameters("prompt", self.prompt(""))
        if self.reasoning:
            self.extra_body["reasoning"] = {"effort": self.reasoning}
            self.add_cache_impact_parameters("reasoning", self.reasoning)
        self.thinking = thinking
        self.context_length = context_length
        if self.thinking:
            # DeepSeek-style thinking switch: {"type": "enabled"|"disabled"}
            self.extra_body["thinking"] = {"type": self.thinking}
            self.add_cache_impact_parameters("thinking", self.thinking)

        # Kimi 模型特殊处理
        # kimi-k3: 使用 reasoning_effort 参数（顶层参数，不支持 thinking）
        # kimi-k2.6: 使用 thinking.type 参数（extra_body）
        self._kimi_reasoning_effort = None  # 用于 kimi-k3 的顶层参数
        if "kimi-k3" in model.lower():
            # kimi-k3 始终启用思考，使用 reasoning_effort 控制推理强度
            self._kimi_reasoning_effort = "low"
            self.add_cache_impact_parameters("reasoning_effort", "low")
            logger.info("Kimi K3 模型已设置 reasoning_effort=low: model=%s", model)
        elif "kimi" in model.lower() or (base_url and "moonshot" in base_url.lower()):
            # kimi-k2.6 及其他 Kimi 模型，禁用 thinking 模式
            if "thinking" not in self.extra_body:
                self.extra_body["thinking"] = {"type": "disabled"}
                self.add_cache_impact_parameters("thinking", "disabled")
                logger.info("Kimi K2.x 模型已禁用 thinking 模式: model=%s, extra_body=%s", model, self.extra_body)

        # 添加详细日志用于诊断 Kimi 问题
        logger.info(
            "OpenAITranslator 初始化: model=%s, base_url=%s, extra_body=%s, reasoning_effort=%s",
            model, base_url, self.extra_body, self._kimi_reasoning_effort,
        )
        if self.enable_json_mode_if_requested:
            self.add_cache_impact_parameters(
                "enable_json_mode_if_requested", self.enable_json_mode_if_requested
            )
        self.token_count = AtomicInteger()
        self.prompt_token_count = AtomicInteger()
        self.completion_token_count = AtomicInteger()
        self.cache_hit_prompt_token_count = AtomicInteger()

    @retry(
        retry=retry_if_exception(_is_retryable_error),
        stop=stop_after_attempt(10),
        wait=_custom_wait,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def do_translate(self, text, rate_limit_params: dict = None) -> str:
        options = {}
        if self.send_temperature:
            options.update(self.options)

        # 构建额外参数（包括 kimi-k3 的 reasoning_effort）
        extra_kwargs = {}
        if hasattr(self, '_kimi_reasoning_effort') and self._kimi_reasoning_effort:
            extra_kwargs['reasoning_effort'] = self._kimi_reasoning_effort

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                **options,

                messages=self.prompt(text),
                extra_body=self.extra_body,
                **extra_kwargs,
            )
        except Exception as e:
            logger.error(
                "API 调用失败: model=%s, base_url=%s, error=%s",
                self.model,
                self.client.base_url,
                str(e),
            )
            raise
        self.update_token_count(response)
        if not response.choices:
            logger.warning(
                "API 返回空 choices（可能被内容过滤），返回原文: %s...",
                text[:80],
            )
            # 添加额外日志帮助诊断
            logger.debug(
                "API 响应详情: model=%s, base_url=%s, usage=%s, response=%s",
                self.model,
                self.client.base_url,
                getattr(response, 'usage', 'N/A'),
                str(response)[:500],
            )
            return text
        content = response.choices[0].message.content
        if content is None or (isinstance(content, str) and not content.strip()):
            # 处理 content 为 None 或空字符串的情况
            reasoning = getattr(response.choices[0].message, "reasoning_content", None)
            if reasoning:
                logger.warning("message.content is empty, falling back to reasoning_content")
                content = reasoning
            else:
                logger.warning(f"API returned empty content for text (len={len(text)}), returning original text")
                return text
        stripped = content.strip()
        if not stripped:
            logger.warning(f"API returned empty content for text (len={len(text)}), returning original text")
            return text
        stripped = self._extract_translation_from_output(stripped, text)
        return stripped

    @staticmethod
    def _extract_translation_from_output(output: str, original_text: str) -> str:
        """从推理链/分析文本中提取纯译文，仅当检测到推理链特征时才介入"""
        return _extract_translation_from_output(output, original_text)

    def prompt(self, text):
        return [
            {
                "role": "system",
                "content": "You are a professional,authentic machine translation engine.",
            },
            {
                "role": "user",
                "content": f";; Treat next line as plain text input and translate it into {self.lang_out}, output translation ONLY. You MUST translate all natural language sentences into {self.lang_out}. Only keep the original text unchanged for: pure numbers, URLs, email addresses, code identifiers, LaTeX/math formulas (e.g. {{1}}), and single proper nouns without meaning. Do NOT return English sentences untranslated. NO explanations. NO notes. Input:\n\n{text}",
            },
        ]

    @retry(
        retry=retry_if_exception(_is_retryable_error),
        stop=stop_after_attempt(10),
        wait=_custom_wait,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def do_llm_translate(self, text, rate_limit_params: dict = None):
        if text is None:
            return None

        options = {}
        if self.send_temperature:
            options.update(self.options)
        if self.enable_json_mode_if_requested and rate_limit_params.get(
            "request_json_mode", False
        ):
            options["response_format"] = {"type": "json_object"}
        max_tokens = 0
        if rate_limit_params:
            max_tokens = int(rate_limit_params.get("max_tokens", 0)) or 0
        input_tokens = int(len(text) * 0.4 + 0.5)

        is_json_mode = (
            rate_limit_params.get("request_json_mode", False)
            if rate_limit_params else False
        )
        output_budget = compute_output_token_budget(self.context_length)
        # 使用模型专属的最大输出限制（如果已知模型名）
        model_name = getattr(self, "model", None)
        if model_name:
            limits = get_model_limits(model_name)
            output_budget = min(output_budget, limits.max_output_tokens)
        if not max_tokens:
            # 输出预算随模型上下文动态调整；长文本需额外空间（6x 输入 + 1024）
            max_tokens = max(output_budget, input_tokens * 6 + 1024)
        if is_json_mode:
            # JSON 批处理需覆盖整批译文，直接取上下文预算上限
            max_tokens = max(max_tokens, output_budget)
        else:
            max_tokens = max(max_tokens, min(output_budget, DEFAULT_TEXT_MIN_TOKENS))

        if self.context_length:
            max_tokens = min(
                max_tokens,
                max(self.context_length - input_tokens, MIN_OUTPUT_TOKENS),
            )

        extra_headers = {}
        if self.send_dashscope_header:
            extra_headers["X-DashScope-DataInspection"] = (
                '{"input": "disable", "output": "disable"}'
            )

        # 构建额外参数（包括 kimi-k3 的 reasoning_effort）
        extra_kwargs = {}
        if hasattr(self, '_kimi_reasoning_effort') and self._kimi_reasoning_effort:
            extra_kwargs['reasoning_effort'] = self._kimi_reasoning_effort

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                **options,
                max_tokens=max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": text,
                    },
                ],
                extra_headers=extra_headers,
                extra_body=self.extra_body,
                **extra_kwargs,
            )
            self.update_token_count(response)
            if not response.choices:
                logger.warning(
                    "API 返回空 choices（可能被内容过滤），返回原文: %s...",
                    text[:80],
                )
                return text
            finish_reason = getattr(response.choices[0], "finish_reason", None)
            if finish_reason == "length":
                logger.warning(
                    f"llm_translate output was truncated by token limit "
                    f"(max_tokens={max_tokens}), reset max_tokens may help."
                )
            content = response.choices[0].message.content
            if content is None or (isinstance(content, str) and not content.strip()):
                # 处理 content 为 None 或空字符串的情况
                reasoning = getattr(response.choices[0].message, "reasoning_content", None)
                if reasoning and finish_reason == "length":
                    retry_tokens = max_tokens * 2
                    logger.warning(
                        f"llm_translate: content is empty due to token limit "
                        f"(max_tokens={max_tokens}), retrying with max_tokens={retry_tokens}"
                    )
                    retry_params = dict(rate_limit_params or {})
                    retry_params["max_tokens"] = retry_tokens
                    return self.do_llm_translate(text, retry_params)
                elif reasoning:
                    # Kimi 等模型可能将输出放在 reasoning_content 中
                    logger.warning("llm_translate: content is empty, falling back to reasoning_content")
                    content = reasoning
                else:
                    logger.warning(f"llm_translate: API returned empty content, returning original text (len={len(text) if text else 0})")
                    return text
            stripped = content.strip()
            if not stripped:
                logger.warning(f"llm_translate: API returned empty content after strip, returning original text (len={len(text) if text else 0})")
                return text
            return stripped
        except openai.BadRequestError as e:
            if (
                "系统检测到输入或生成内容可能包含不安全或敏感内容，请您避免输入易产生敏感内容的提示语，感谢您的配合。"
                in e.message
            ):
                raise ContentFilterError(e.message) from e
            else:
                raise

    def update_token_count(self, response):
        try:
            if response.usage and response.usage.total_tokens:
                self.token_count.inc(response.usage.total_tokens)
            if response.usage and response.usage.prompt_tokens:
                self.prompt_token_count.inc(response.usage.prompt_tokens)
            if response.usage and response.usage.completion_tokens:
                self.completion_token_count.inc(response.usage.completion_tokens)
            # Support both response.usage.prompt_cache_hit_tokens and response.prompt_tokens_details.cached_tokens
            hit_count = 0
            if response.usage and hasattr(response.usage, "prompt_cache_hit_tokens"):
                hit_count = getattr(response.usage, "prompt_cache_hit_tokens", 0)
            if hasattr(response, "prompt_tokens_details") and getattr(
                response.prompt_tokens_details, "cached_tokens", 0
            ):
                hit_count += getattr(response.prompt_tokens_details, "cached_tokens", 0)
            if hit_count:
                self.cache_hit_prompt_token_count.inc(hit_count)
        except Exception:
            logger.exception("Error updating token count")


    def get_rich_text_left_placeholder(self, placeholder_id: int | str):
        return (
            f"<style id='{placeholder_id}'>",
            f"<\\s*style\\s*id\\s*=\\s*'\\s*{placeholder_id}\\s*'\\s*>",
        )

    def get_rich_text_right_placeholder(self, placeholder_id: int | str):
        return "</style>", r"<\s*\/\s*style\s*>"
