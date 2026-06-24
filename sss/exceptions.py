class SssError(Exception):
    """Base error for all sss failures (connection, sync, primitives, scripts)."""

    def __init__(self, message: str, returncode: int = None, stderr: str = None):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr
