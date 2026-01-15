import grpc


class MotorClient:
    def __init__(self, address: str):
        self._address = address
        self._channel: grpc.aio.Channel | None = None

    async def connect(self) -> None:
        self._channel = grpc.aio.insecure_channel(self._address)

    async def close(self) -> None:
        if self._channel:
            await self._channel.close()

    async def select(
        self,
        experiment_id: str,
        context_id: str,
        context_vector: list[float],
        context_metadata: dict
    ) -> dict:
        # TODO: Use generated proto stubs
        # stub = motor_pb2_grpc.MotorServiceStub(self._channel)
        # request = motor_pb2.SelectRequest(...)
        # response = await stub.Select(request)
        raise NotImplementedError("Proto stubs not generated yet")
