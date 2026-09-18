from openbot.api.bots import _known_tool


def test_configured_mcp_tools_are_known_when_disconnected():
    class Registry:
        @staticmethod
        def has(name):
            return False

    class Mcp:
        @staticmethod
        def has(name):
            return name == "remote"

    services = type("Services", (), {"registry": Registry(), "mcp": Mcp()})()
    assert _known_tool(services, "remote__pending_tool")
    assert not _known_tool(services, "missing__tool")
