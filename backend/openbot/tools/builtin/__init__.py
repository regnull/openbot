from openbot.tools.builtin.bot_profiles import (
                    read_bot_description,
                    read_bot_instructions,
                    update_bot_description,
                    update_bot_instructions,
)
from openbot.tools.builtin.bots import create_bot
from openbot.tools.builtin.files import edit_file, list_files, patch_file, read_file, write_file
from openbot.tools.builtin.http import fetch_url, http_request
from openbot.tools.builtin.scratchpad import scratchpad
from openbot.tools.builtin.search import find_files, search_code
from openbot.tools.builtin.shell import run_shell
from openbot.tools.builtin.skills import load_skill
from openbot.tools.builtin.todo import todo_write

SELECTABLE_TOOLS = [run_shell, read_file, write_file, edit_file, patch_file, list_files, search_code, find_files, http_request, fetch_url, create_bot,
                    read_bot_description, read_bot_instructions, update_bot_description, update_bot_instructions, todo_write, scratchpad, load_skill]
