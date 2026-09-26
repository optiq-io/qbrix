"""unit tests for context properties over the grpc select servicer.

invariants verified:
  - a Struct properties field reaches ProxyService.select as a plain dict
  - numeric properties survive the hop as numbers, not strings
  - an unset repeated vector is passed as None, not [], so a properties-only
    call is not mistaken for supplying both channels
  - a supplied vector still reaches the service unchanged
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from google.protobuf import struct_pb2

from qbrixproto import common_pb2
from qbrixproto import proxy_pb2

from proxysvc.server import ProxyGRPCServicer


def _servicer(service):
    servicer = ProxyGRPCServicer(service)
    # shadow the staticmethod that reads the interceptor's auth contextvar
    servicer._get_tenant_id = lambda: "dev-tenant"
    return servicer


def _service():
    service = AsyncMock()
    service.select.return_value = {
        "arm": {"id": "a-0", "name": "control", "index": 0},
        "request_id": "tok",
        "is_default": False,
    }
    return service


def _request(**context_kwargs):
    return proxy_pb2.SelectRequest(
        experiment_id="exp-1",
        context=common_pb2.Context(id="u-1", **context_kwargs),
    )


class TestSelectProperties:
    async def test_properties_reach_the_service_as_a_dict(self):
        service = _service()
        properties = struct_pb2.Struct()
        properties.update({"device": "mobile", "price": 20, "returning": True})

        await _servicer(service).Select(_request(properties=properties), None)

        kwargs = service.select.await_args.kwargs
        assert kwargs["context_properties"] == {
            "device": "mobile",
            "price": 20,
            "returning": True,
        }

    async def test_numeric_property_survives_as_a_number(self):
        """the whole reason this is a Struct and not a map<string, string>."""
        service = _service()
        properties = struct_pb2.Struct()
        properties.update({"price": 20})

        await _servicer(service).Select(_request(properties=properties), None)

        price = service.select.await_args.kwargs["context_properties"]["price"]
        assert price == 20
        assert not isinstance(price, str)

    async def test_unset_vector_is_passed_as_none(self):
        """a repeated proto3 field has no presence: unset arrives as [].

        passing that through would look like both channels at once and every
        properties-only grpc call would be rejected.
        """
        service = _service()
        properties = struct_pb2.Struct()
        properties.update({"device": "mobile"})

        await _servicer(service).Select(_request(properties=properties), None)

        assert service.select.await_args.kwargs["context_vector"] is None

    async def test_unset_properties_are_passed_as_none(self):
        service = _service()

        await _servicer(service).Select(_request(vector=[0.1, 0.2]), None)

        kwargs = service.select.await_args.kwargs
        assert kwargs["context_properties"] is None
        assert kwargs["context_vector"] == pytest.approx([0.1, 0.2])

    async def test_neither_channel_passes_both_as_none(self):
        service = _service()

        await _servicer(service).Select(_request(), None)

        kwargs = service.select.await_args.kwargs
        assert kwargs["context_vector"] is None
        assert kwargs["context_properties"] is None
