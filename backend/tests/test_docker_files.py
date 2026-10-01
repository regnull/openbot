from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_docker_entrypoint_is_checked_out_with_linux_line_endings():
    entrypoint = REPO / "docker-entrypoint.sh"
    attributes = REPO / ".gitattributes"

    assert entrypoint.read_bytes().count(b"\r\n") == 0
    assert "docker-entrypoint.sh text eol=lf" in attributes.read_text()
