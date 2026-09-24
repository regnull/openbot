from openbot.api.tool_validation import known_tool


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
    assert known_tool(services, "remote__pending_tool")
    assert not known_tool(services, "missing__tool")
