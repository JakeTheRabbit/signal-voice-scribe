class ControlFailure(Exception):
    """An actionable, renderer-safe failure (never include raw exception text)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
