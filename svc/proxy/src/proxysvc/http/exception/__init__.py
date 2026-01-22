from proxysvc.http.exception.base import BaseAPIException
from proxysvc.http.exception.base import BadRequestException
from proxysvc.http.exception.base import UnauthorizedException
from proxysvc.http.exception.base import ForbiddenException
from proxysvc.http.exception.base import NotFoundException
from proxysvc.http.exception.base import ConflictException
from proxysvc.http.exception.base import RateLimitedException
from proxysvc.http.exception.base import InternalServerException
from proxysvc.http.exception.base import ServiceUnavailableException
from proxysvc.http.exception.base import PoolNotFoundException
from proxysvc.http.exception.base import ExperimentNotFoundException
from proxysvc.http.exception.base import UserNotFoundException
from proxysvc.http.exception.base import GateNotFoundException
from proxysvc.http.exception.base import InvalidTokenException
from proxysvc.http.exception.base import InvalidAPIKeyException
from proxysvc.http.exception.base import InsufficientScopesException
from proxysvc.http.exception.base import UserAlreadyExistsException
from proxysvc.http.exception.base import APIKeyLimitException
from proxysvc.http.exception.base import PoolCreationException
from proxysvc.http.exception.base import ExperimentCreationException
from proxysvc.http.exception.base import SelectionException
from proxysvc.http.exception.base import FeedbackException

__all__ = [
    "BaseAPIException",
    "BadRequestException",
    "UnauthorizedException",
    "ForbiddenException",
    "NotFoundException",
    "ConflictException",
    "RateLimitedException",
    "InternalServerException",
    "ServiceUnavailableException",
    "PoolNotFoundException",
    "ExperimentNotFoundException",
    "UserNotFoundException",
    "GateNotFoundException",
    "InvalidTokenException",
    "InvalidAPIKeyException",
    "InsufficientScopesException",
    "UserAlreadyExistsException",
    "APIKeyLimitException",
    "PoolCreationException",
    "ExperimentCreationException",
    "SelectionException",
    "FeedbackException",
]