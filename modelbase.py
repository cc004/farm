from re import T
from typing import Generic, TypeVar

class ResponseBase:
    pass

TResponse = TypeVar('TResponse', bound=ResponseBase)

class ResponseHeader:
    sid: str = None
    request_id: str = None
    viewer_id: str = None
    servertime: int = 0
    result_code: int = -1
    short_udid: str = None

class Response(Generic[TResponse]):
    data_headers: ResponseHeader = None
    data: TResponse = None

class Request(Generic[TResponse]):
    viewer_id: str = None
    
    @property
    def crypted(self) -> bool: True

    @property
    def url(self) -> str:
        raise NotImplementedError()