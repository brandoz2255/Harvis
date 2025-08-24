from .sys_info import register_sys_info
from .exec_cmd import register_exec
from .processes import register_process_tools
from .env_vars import register_env_tools
from .archive import register_archive_tools
from .parse import register_parse_tools
from .pdf_extract import register_pdf_tools
from .word_extract import register_word_tools

def register_os_ops():
    register_sys_info()
    register_exec()
    register_process_tools()
    register_env_tools()
    register_archive_tools()
    register_parse_tools()
    register_pdf_tools()
    register_word_tools()
