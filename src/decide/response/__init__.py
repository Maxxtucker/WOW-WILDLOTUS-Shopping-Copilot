"""Purpose: response package.

Input: state, retriever, candidate ASINs, Plan, slate.
Output: official respond dict, and writeback of last_slate / reply_value_lookup.
Role: protocol assembly and session writeback. See README.md.
"""

from .builder import ResponseBuilder, build_message, build_response
from .writeback import persist_turn, record_action, set_reply_options

__all__ = [
    "ResponseBuilder",
    "build_message",
    "build_response",
    "persist_turn",
    "record_action",
    "set_reply_options",
]
