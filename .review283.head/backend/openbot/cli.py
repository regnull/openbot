"""Command-line entry point for the OpenBot backend."""
from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    args, uvicorn_args = _parse_args()
    _apply_detail_setting(args)
    if args.root_directory:
        os.environ["OPENBOT_ROOT_DIRECTORY"] = args.root_directory
    options = _uvicorn_options(uvicorn_args)
    _apply_listen_port(options)
    uvicorn.run("openbot.main:app", **options)


def _apply_listen_port(options: dict[str, object]) -> None:
    """Tell Settings which port this server listens on, so a local PUBLIC_URL (the OAuth redirect
    target) follows it instead of pointing at :8000 while e.g. `make app` serves on :8001."""
    if "port" in options:
        os.environ["OPENBOT_LISTEN_PORT"] = str(options["port"])


def _apply_detail_setting(args: argparse.Namespace) -> None:
    """Apply the optional detail setting without changing ordinary environment-based startup."""
    if args.include_llm_call_details:
        os.environ["OPENBOT_INCLUDE_LLM_CALL_DETAILS"] = "true"
    elif args.exclude_llm_call_details:
        os.environ["OPENBOT_INCLUDE_LLM_CALL_DETAILS"] = "false"


def _parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="Run the OpenBot backend.")
    details = parser.add_mutually_exclusive_group()
    details.add_argument("--include-llm-call-details", action="store_true",
                         help="include per-model-call token details in activity events")
    details.add_argument("--exclude-llm-call-details", action="store_true",
                         help="omit per-model-call token details from activity events")
    parser.add_argument("--root-directory", help="root directory for default workspace and database paths")
    return parser.parse_known_args(argv)


def _uvicorn_options(args: list[str]) -> dict[str, object]:
    """Translate the small set of launcher options used by Make/Electron."""
    options: dict[str, object] = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--reload":
            options["reload"] = True
        elif arg == "--reload-dir":
            i += 1
            options.setdefault("reload_dirs", []).append(args[i])
        elif arg == "--port":
            i += 1
            options["port"] = int(args[i])
        elif arg == "--host":
            i += 1
            options["host"] = args[i]
        i += 1
    return options


if __name__ == "__main__":
    main()
