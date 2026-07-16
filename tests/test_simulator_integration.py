import asyncio
import socket

from lightbeacon.config import Settings
from lightbeacon.database import Database
from lightbeacon.events import EventBroker
from lightbeacon.models import EffectRequest
from lightbeacon.protocol import EffectMode
from lightbeacon.simulator import SimulatedNode, SimulatorOptions
from lightbeacon.udp_controller import UdpController


async def test_controller_discovers_and_controls_simulated_node(tmp_path) -> None:
    settings = Settings.for_test(tmp_path, udp_port=0)
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    controller = UdpController(settings, database, EventBroker())
    await controller.start()
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: SimulatedNode(
            0,
            SimulatorOptions(
                "127.0.0.1", controller.bound_port, settings.hmac_key, 0, 0
            ),
        ),
        local_addr=("127.0.0.1", 0),
        family=socket.AF_INET,
    )
    try:
        await asyncio.sleep(2.4)
        nodes = controller.list_nodes()
        assert len(nodes) == 1
        assert nodes[0].node_id == "LB-001"
        result = await controller.set_effect(
            EffectRequest(
                node_ids=["LB-001"],
                mode=EffectMode.BLINK_BLUE,
                period_ms=1000,
                brightness=25,
            )
        )
        assert result.results == {"LB-001": "accepted"}
    finally:
        transport.close()
        await controller.close()
        database.close()

