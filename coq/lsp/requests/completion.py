from pathlib import Path
from typing import Iterator, Sequence, Tuple, cast

from pynvim.api.nvim import Nvim

from ...registry import atomic
from ...shared.timeit import timeit
from ...shared.types import UTF16, Completion, Context
from ..parse import parse
from ..types import CompletionResponse
from .request import blocking_request

_LUA = (Path(__file__).resolve().parent / "completion.lua").read_text("UTF-8")

atomic.exec_lua(_LUA, ())


def request(
    nvim: Nvim,
    short_name: str,
    tie_breaker: int,
    context: Context,
) -> Iterator[Tuple[bool, Sequence[Completion]]]:

    row, c = context.position
    col = len(context.line_before[:c].encode(UTF16)) // 2

    for reply in blocking_request(nvim, "COQlsp_comp", (row, col)):
        resp = cast(CompletionResponse, reply)
        yield parse(short_name, tie_breaker=tie_breaker, resp=resp)

