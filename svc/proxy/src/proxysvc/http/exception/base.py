from fastapi import HTTPException


class BaseProxyAPIException(HTTPException):
    """base exception for proxy api errors."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)


class BaseEngineException(HTTPException):
    """base exception for engine errors."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)
