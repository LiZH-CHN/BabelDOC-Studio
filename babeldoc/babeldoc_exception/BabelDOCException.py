class ScannedPDFError(Exception):
    def __init__(self, message):
        super().__init__(message)


class ExtractTextError(Exception):
    def __init__(self, message):
        super().__init__(message)


class InputFileGeneratedByBabelDOCError(Exception):
    def __init__(self, message):
        super().__init__(message)


class ContentFilterError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class LayoutException(Exception):
    """排版/公式结构异常 - 触发后应降级为图片块处理而非闪退"""

    def __init__(self, message, page: int = 0, recoverable: bool = True):
        super().__init__(message)
        self.message = message
        self.page = page
        self.recoverable = recoverable
