import contextlib
import logging
import threading
import time
import unicodedata
from abc import ABC
from abc import abstractmethod

import httpx
import openai
from tenacity import before_sleep_log
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_exponential

from babeldoc.babeldoc_exception.BabelDOCException import ContentFilterError
from babeldoc.translator.cache import TranslationCache
from babeldoc.utils.atomic_integer import AtomicInteger

logger = logging.getLogger(__name__)


def remove_control_characters(s):
    return "".join(ch for ch in s if unicodedata.category(ch)[0] != "C")


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
        """
        with self.lock:
            now = time.monotonic()

            wait_duration = self.next_request_time - now
            if wait_duration > 0:
                time.sleep(wait_duration)

            # Update the next allowed request time.
            # If the limiter has been idle, the next request should start from 'now'.
            now = time.monotonic()
            self.next_request_time = (
                max(self.next_request_time, now) + self.min_interval
            )

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
        self.client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key,
            http_client=httpx.Client(
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
        if self.thinking:
            # DeepSeek-style thinking switch: {"type": "enabled"|"disabled"}
            self.extra_body["thinking"] = {"type": self.thinking}
            self.add_cache_impact_parameters("thinking", self.thinking)
        if self.enable_json_mode_if_requested:
            self.add_cache_impact_parameters(
                "enable_json_mode_if_requested", self.enable_json_mode_if_requested
            )
        self.token_count = AtomicInteger()
        self.prompt_token_count = AtomicInteger()
        self.completion_token_count = AtomicInteger()
        self.cache_hit_prompt_token_count = AtomicInteger()

    @retry(
        retry=retry_if_exception_type(openai.RateLimitError),
        stop=stop_after_attempt(100),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def do_translate(self, text, rate_limit_params: dict = None) -> str:
        options = {}
        if self.send_temperature:
            options.update(self.options)

        response = self.client.chat.completions.create(
            model=self.model,
            **options,

            messages=self.prompt(text),
            extra_body=self.extra_body,
        )
        self.update_token_count(response)
        content = response.choices[0].message.content
        if content is None:
            reasoning = getattr(response.choices[0].message, "reasoning_content", None)
            if reasoning:
                logger.warning("message.content is None, falling back to reasoning_content")
                content = reasoning
            else:
                logger.warning(f"API returned None content for text (len={len(text)}), returning original text")
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
        if len(output) < 50:
            return output

        import re

        # 检测推理链特征：编号步骤 + 分析关键词
        cot_patterns = [
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
        is_cot = any(re.search(p, output) for p in cot_patterns)
        if not is_cot:
            return output

        # 预处理：移除推理旁白（括号内内容、行内注释）
        # 步骤1：移除所有括号及括号内的内容（推理旁白）
        cleaned = re.sub(r'\s*\([^)]*\)', '', output)
        # 步骤2：移除行内推理注释（- wait, ... / — Let's ... 等）
        cleaned = re.sub(r'\s*[-—–]\s*(?:wait|let[\'\u2019]s|actually|hmm|but\s+wait).*', '', cleaned, flags=re.IGNORECASE)
        # 步骤3：仅移除推理关键词及其后最多3个词，不删除到行尾
        cleaned = re.sub(
            r'\b(?:wait|let[\'\u2019]s|actually|hmm|but\s+wait|or\s+just|stick\s+closer)[\s,.]*(?:\S+\s*){0,3}',
            '', cleaned, flags=re.IGNORECASE,
        )

        # 方法1：匹配 "Translation:" 行后的内容
        matches = re.findall(
            r'(?:^|\n)\s*\*?\s*Translation\s*:?\s*(.+)',
            cleaned, re.MULTILINE | re.IGNORECASE,
        )
        if matches:
            return matches[-1].strip()

        # 方法2：提取 "Translate" 章节（到下一个编号步骤为止）
        translate_section = re.search(
            r'(?:^|\n)\d+\.\s*\*{1,2}[Tt]ranslate.+?\*{1,2}[ \t]*\n?(.*?)(?:\n\s*\d+\.\s*\*|$)',
            cleaned, re.DOTALL,
        )
        if translate_section:
            section_text = translate_section.group(1).strip()
            # 从该章节中提取纯中文行（过滤英文推理行）
            cn_lines = re.findall(
                r'(?:^|\n)[ \t]*[\u4e00-\u9fff][^\n]{5,}',
                section_text, re.MULTILINE,
            )
            if cn_lines:
                combined = '\n'.join(l.strip() for l in cn_lines)
                if len(combined) > 10:
                    return combined

        # 方法3：从清理后的文本中提取箭头格式译文（含推理词的已去除）
        arrow_matches = []
        for m in re.finditer(r'(?:->|→)\s*(.+?)(?:\s*\n|\s*$)', cleaned):
            target = m.group(1)
            if not re.search(r'[\u4e00-\u9fff]', target):
                continue
            # 检查目标本身是否包含推理旁白
            if re.search(r'\b(?:wait|let[\'\u2019]s|actually|hmm|but\s+wait|or\s+just|stick\s+closer)\b', target, re.IGNORECASE):
                continue
            # 过滤明显太短的片段（可能是占位翻译）
            if len(target.strip()) < 3:
                continue
            arrow_matches.append(target.strip())
        if arrow_matches:
            combined = ''.join(arrow_matches)
            if len(combined) > 10:
                return combined

        # 方法4：从清理后的文本中提取含"翻译"/"译文"标记的段落
        cn_fallback = re.findall(
            r'(?:^|\n).*?(?:翻译|译文)[：:]\s*([\u4e00-\u9fff][^\n]{4,})',
            cleaned, re.MULTILINE,
        )
        if cn_fallback:
            candidate = cn_fallback[-1].strip()
            if len(candidate) > 5:
                return candidate

        # 方法5：提取最后一个包含"翻译结果"/"最终输出"标记的段落
        result_hint = re.search(
            r'(?:^|\n).*?(?:翻译结果|译文[：:]|最终输出|翻译[：:]\s*)([\u4e00-\u9fff][^\n]{4,})',
            cleaned, re.MULTILINE,
        )
        if result_hint:
            candidate = result_hint.group(1).strip()
            if len(candidate) > 5:
                return candidate

        # 方法6：从清理后的整个文本中提取最长的中文文本段（不限行首位置）
        cn_blocks = re.findall(
            r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef][^\n]{9,})',
            cleaned,
        )
        if cn_blocks:
            # 过滤掉含推理关键词的块
            filtered = [b for b in cn_blocks if not re.search(
                r'\b(?:wait|let[\'\u2019]s|actually|hmm|but\s+wait|or\s+just|stick\s+closer|analysis|analyze|role|review)\b',
                b, re.IGNORECASE,
            )]
            if filtered:
                # 返回最长的一个
                best = max(filtered, key=len)
                return best.strip()
            # 如果全被过滤，返回最长的一个（总比推理碎片好）
            return max(cn_blocks, key=len).strip()

        # 方法7：提取所有较短中文连续段（≥3字符），合并后返回
        all_cn = re.findall(
            r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]{2,}[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]?[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]*)',
            cleaned,
        )
        if all_cn:
            combined = ''.join(all_cn)
            if len(combined) >= 5:
                return combined.strip()

        # 无法安全提取 → 如果清理后的文本包含中文，返回清理后文本；否则回退到原文本
        if re.search(r'[\u4e00-\u9fff]', cleaned) and len(cleaned.strip()) > 5:
            return cleaned.strip()
        return original_text

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
        retry=retry_if_exception_type(openai.RateLimitError),
        stop=stop_after_attempt(100),
        wait=wait_exponential(multiplier=1, min=1, max=15),
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
        if not max_tokens:
            input_tokens = int(len(text) * 0.4 + 0.5)
            max_tokens = max(8192, input_tokens * 6 + 1024)

        is_json_mode = (
            rate_limit_params.get("request_json_mode", False)
            if rate_limit_params else False
        )
        min_tokens = 4096 if is_json_mode else 8192
        max_tokens = max(max_tokens, min_tokens)

        extra_headers = {}
        if self.send_dashscope_header:
            extra_headers["X-DashScope-DataInspection"] = (
                '{"input": "disable", "output": "disable"}'
            )
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
            )
            self.update_token_count(response)
            finish_reason = getattr(response.choices[0], "finish_reason", None)
            if finish_reason == "length":
                logger.warning(
                    f"llm_translate output was truncated by token limit "
                    f"(max_tokens={max_tokens}), reset max_tokens may help."
                )
            content = response.choices[0].message.content
            if content is None:
                reasoning = getattr(response.choices[0].message, "reasoning_content", None)
                if reasoning and finish_reason == "length":
                    retry_tokens = max_tokens * 2
                    logger.warning(
                        f"llm_translate: content is None due to token limit "
                        f"(max_tokens={max_tokens}), retrying with max_tokens={retry_tokens}"
                    )
                    retry_params = dict(rate_limit_params or {})
                    retry_params["max_tokens"] = retry_tokens
                    return self.do_llm_translate(text, retry_params)
                elif reasoning:
                    logger.warning("llm_translate: content is None, falling back to reasoning_content")
                    content = reasoning
                else:
                    logger.warning(f"llm_translate: API returned None content, returning original text (len={len(text) if text else 0})")
                    return text
            stripped = content.strip()
            if not stripped:
                logger.warning(f"llm_translate: API returned empty content, returning original text (len={len(text) if text else 0})")
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
        except Exception as e:
            logger.exception("Error updating token count")

    def get_formular_placeholder(self, placeholder_id: int | str):
        return "{v" + str(placeholder_id) + "}", f"{{\\s*v\\s*{placeholder_id}\\s*}}"
        return "{{" + str(placeholder_id) + "}}"

    def get_rich_text_left_placeholder(self, placeholder_id: int | str):
        return (
            f"<style id='{placeholder_id}'>",
            f"<\\s*style\\s*id\\s*=\\s*'\\s*{placeholder_id}\\s*'\\s*>",
        )

    def get_rich_text_right_placeholder(self, placeholder_id: int | str):
        return "</style>", r"<\s*\/\s*style\s*>"
