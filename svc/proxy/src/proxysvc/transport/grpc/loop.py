from __future__ import annotations

from datetime import timezone

from google.protobuf import struct_pb2
from google.protobuf import timestamp_pb2
from google.protobuf.json_format import MessageToDict

from qbrixproto import loop_pb2
from qbrixproto import loop_pb2_grpc

from proxysvc.server import unstruct
from proxysvc.service import ProxyService
from proxysvc.transport.grpc.auth.context import get_grpc_auth_context
from proxysvc.transport.grpc.exception.base import UnauthenticatedException


def _struct(value: dict) -> struct_pb2.Struct:
    struct = struct_pb2.Struct()
    struct.update(value)
    return struct


class LoopGRPCServicer(loop_pb2_grpc.LoopServiceServicer):
    """select(loop, context) and outcome(request_id, value) over grpc,
    answering as the http routes do."""

    def __init__(self, service: ProxyService):
        self._service = service

    async def Select(self, request, context):
        auth_ctx = get_grpc_auth_context()
        if auth_ctx is None:
            raise UnauthenticatedException("authentication context not available")
        properties = (
            unstruct(MessageToDict(request.context.properties))
            if request.context.HasField("properties")
            else None
        )
        answer = await self._service.select_loop(
            auth_ctx.tenant_id, request.loop, request.context.unit, properties
        )
        option = answer["option"]
        return loop_pb2.SelectResponse(
            option=loop_pb2.Option(
                key=option["key"],
                name=option["name"],
                config=_struct(option["config"]),
            ),
            request_id=answer["request_id"] or "",
            reason=answer["reason"],
        )

    async def Outcome(self, request, context):
        auth_ctx = get_grpc_auth_context()
        if auth_ctx is None:
            raise UnauthenticatedException("authentication context not available")
        at = (
            request.at.ToDatetime(tzinfo=timezone.utc)
            if request.HasField("at")
            else None
        )
        answer = await self._service.outcome(
            auth_ctx.tenant_id,
            request.request_id,
            request.value if request.HasField("value") else None,
            request.id or None,
            at,
        )
        recorded_at = timestamp_pb2.Timestamp()
        recorded_at.FromMilliseconds(answer["at_ms"])
        return loop_pb2.OutcomeResponse(id=answer["id"], at=recorded_at)
