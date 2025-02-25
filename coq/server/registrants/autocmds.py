from asyncio import Handle
from asyncio.events import AbstractEventLoop
from contextlib import suppress
from typing import Optional

from pynvim.api.nvim import Nvim, NvimError
from pynvim_pp.api import (
    buf_filetype,
    buf_get_option,
    buf_name,
    cur_buf,
    get_cwd,
    win_close,
)
from pynvim_pp.float_win import list_floatwins
from pynvim_pp.lib import async_call, awrite, go
from std2.locale import si_prefixed_smol

from ...lang import LANG
from ...registry import NAMESPACE, atomic, autocmd, rpc
from ...tmux.parse import snapshot
from ...treesitter.request import async_request
from ..rt_types import Stack
from ..state import state


@rpc(blocking=True)
def _kill_float_wins(nvim: Nvim, stack: Stack) -> None:
    wins = tuple(list_floatwins(nvim))
    if len(wins) != 2:
        for win in wins:
            win_close(nvim, win=win)


_ = autocmd("WinEnter") << f"lua {NAMESPACE}.{_kill_float_wins.name}()"


@rpc(blocking=True)
def _new_cwd(nvim: Nvim, stack: Stack) -> None:
    cwd = get_cwd(nvim)

    async def cont() -> None:
        s = state(cwd=cwd)
        await stack.ctdb.swap(s.cwd)

    go(nvim, aw=cont())


_ = autocmd("DirChanged") << f"lua {NAMESPACE}.{_new_cwd.name}()"


@rpc(blocking=True)
def _ft_changed(nvim: Nvim, stack: Stack) -> None:
    buf = cur_buf(nvim)
    ft = buf_filetype(nvim, buf=buf)
    filename = buf_name(nvim, buf=buf)

    async def cont() -> None:
        await stack.bdb.buf_update(buf.number, filetype=ft, filename=filename)

    go(nvim, aw=cont())


_ = autocmd("FileType") << f"lua {NAMESPACE}.{_ft_changed.name}()"
atomic.exec_lua(f"{NAMESPACE}.{_ft_changed.name}()", ())


@rpc(blocking=True)
def _insert_enter(nvim: Nvim, stack: Stack) -> None:
    ts = stack.settings.clients.tree_sitter
    nono_bufs = state().nono_bufs
    buf = cur_buf(nvim)

    async def cont() -> None:
        if ts.enabled and buf.number not in nono_bufs:
            if payload := await async_request(nvim, lines_around=ts.search_context):
                await stack.tdb.populate(
                    payload.buf,
                    filetype=payload.filetype,
                    filename=payload.filename,
                    nodes=payload.payloads,
                )
                if payload.elapsed > ts.slow_threshold:
                    state(nono_bufs={buf.number})
                    msg = LANG(
                        "source slow",
                        source=ts.short_name,
                        elapsed=si_prefixed_smol(payload.elapsed, precision=0),
                    )
                    await awrite(nvim, msg, error=True)

    go(nvim, aw=cont())


_ = autocmd("InsertEnter") << f"lua {NAMESPACE}.{_insert_enter.name}()"


@rpc(blocking=True)
def _on_focus(nvim: Nvim, stack: Stack) -> None:
    async def cont() -> None:
        current, panes = await snapshot(
            stack.settings.clients.tmux.all_sessions,
            unifying_chars=stack.settings.match.unifying_chars,
        )
        await stack.tmdb.periodical(current, panes=panes)

    go(nvim, aw=cont())


_ = autocmd("FocusGained") << f"lua {NAMESPACE}.{_on_focus.name}()"

_HANDLE: Optional[Handle] = None


@rpc(blocking=True)
def _when_idle(nvim: Nvim, stack: Stack) -> None:
    global _HANDLE
    if _HANDLE:
        _HANDLE.cancel()

    def cont() -> None:
        with suppress(NvimError):
            buf = cur_buf(nvim)
            buf_type: str = buf_get_option(nvim, buf=buf, key="buftype")
            if buf_type == "terminal":
                nvim.api.buf_detach(buf)
                state(nono_bufs={buf.number})

        _insert_enter(nvim, stack=stack)
        stack.supervisor.notify_idle()

    assert isinstance(nvim.loop, AbstractEventLoop)
    nvim.loop.call_later(
        stack.settings.limits.idle_timeout,
        lambda: go(nvim, aw=async_call(nvim, cont)),
    )


_ = autocmd("CursorHold", "CursorHoldI") << f"lua {NAMESPACE}.{_when_idle.name}()"
