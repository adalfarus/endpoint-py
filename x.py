from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    Annotated,
    Callable,
    ClassVar,
    Concatenate,
    Final,
    Generic,
    Iterable,
    Iterator,
    Literal,
    Mapping,
    MutableMapping,
    Never,
    NewType,
    NotRequired,
    Optional,
    ParamSpec,
    Protocol,
    Required,
    Sequence,
    TypedDict,
    TypeAlias,
    TypeGuard,
    TypeVar,
    TypeVarTuple,
    Union,
    Unpack,
    overload,
)
from collections.abc import Awaitable, Coroutine
from datetime import datetime
from decimal import Decimal


# ---------- Shared types / helpers ----------

P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")
Ts = TypeVarTuple("Ts")

UserId = NewType("UserId", int)
Sentinel: Final = object()

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class Meta(TypedDict, total=False):
    trace_id: str
    retries: int
    tags: list[str]


class Payload(TypedDict):
    user: Required[UserId]
    data: Required[JSONValue]
    meta: NotRequired[Meta]


class SupportsClose(Protocol):
    def close(self) -> None: ...


class SupportsGetItem(Protocol[T]):
    def __getitem__(self, key: str) -> T: ...


@dataclass
class Cfg:
    """Cfg used to test dataclass defaults/factories & class vars."""
    host: str = "localhost"
    port: int = 8080
    headers: dict[str, str] = field(default_factory=lambda: {"User-Agent": "tool-test/1.0"})
    created_at: datetime = field(default_factory=datetime.utcnow)
    cache: ClassVar[dict[str, Any]] = {}


# ---------- 1) Signature maximalist ----------

def signature_stress(
    a: int,
    b: str = "x",
    /,
    c: float | None = None,
    d: Annotated[list[tuple[int, str]] | None, "pairs"] = None,
    *args: Annotated[int, "extra ints"],
    e: Annotated[Literal["fast", "slow"], "mode"] = "fast",
    f: Callable[[int, str], JSONValue] = lambda i, s: {"i": i, "s": s},
    g: type[Exception] = ValueError,
    **kwargs: Annotated[Mapping[str, JSONValue], "extra json-ish kv"],
) -> Annotated[dict[str, JSONValue], "result"]:
    """
    Mixed docstring styles + edge cases.

    Args:
        a (int): positional-only.
        b (str, optional): positional-only with default="x".
        c (float | None): can be None.
        d (list[tuple[int, str]] | None): annotated with 'pairs'.
        *args (int): extra ints; note it's variadic.
        e (Literal["fast","slow"]): keyword-only mode.
        f (Callable[[int,str], JSONValue]): default is a lambda (repr is fun).
        g (type[Exception]): exception class.
        **kwargs (Mapping[str, JSONValue]): extra values.

    Returns:
        dict[str, JSONValue]: JSON-ish output.

    Notes:
        - Has /, *, *args, **kwargs, Annotated, Literal.
        - Default lambda is intentionally annoying for doc tools.
    """
    return {"ok": True, "mode": e}


# ---------- 2) Forward refs + recursive types + unions ----------

class Node(TypedDict):
    name: str
    children: list["Node"]
    payload: JSONValue | None


def recursive_tree_op(
    root: "Node",
    /,
    *,
    max_depth: int | None = None,
    visit: Callable[["Node"], JSONValue] | None = None,
    prune: Callable[["Node"], bool] = lambda n: False,
) -> JSONValue:
    """
    Operate on a recursive Node tree.

    Parameters
    ----------
    root : Node
        Root node. (Forward ref is deliberate.)
    max_depth : int | None, keyword-only
        Stop after N levels; None means unlimited.
    visit : Callable[[Node], JSONValue] | None
        Transform function. Default None.
    prune : Callable[[Node], bool]
        If returns True, skip that node. Default lambda.

    Returns
    -------
    JSONValue
        A JSON-like structure derived from traversal.
    """
    return visit(root) if visit else root["payload"]


# ---------- 3) ParamSpec/Concatenate + decorator-like typing ----------

def wrap_with_prefix(
    prefix: str,
) -> Callable[[Callable[[Concatenate[str, P]], R]], Callable[P, R]]:
    """
    Returns a wrapper factory that prepends `prefix` to the first arg.

    This stresses ParamSpec and Concatenate.
    """
    def deco(fn: Callable[[Concatenate[str, P]], R]) -> Callable[P, R]:
        def inner(*args: P.args, **kwargs: P.kwargs) -> R:
            return fn(prefix, *args, **kwargs)
        return inner
    return deco


# ---------- 4) TypeVarTuple/Unpack in both args + return ----------

def tuple_pack_unpack(
    head: T,
    /,
    *items: Unpack[tuple[*Ts]],
    tail: tuple[*Ts],
) -> tuple[T, *Ts, *Ts]:
    """
    Uses TypeVarTuple + Unpack.

    Parameters:
        *items: Unpacked tuple elements (variadic type vars).
        head: positional-only head.
        tail: positional-only? (No; it's positional-or-keyword but after /.)
              Actually: after '/', tail is positional-or-keyword unless '*' appears.
              This is intentional to see if your tool gets it right.

    Returns:
        tuple: (head, *items, *tail) with repeated Ts.
    """
    return (head, *items, *tail)


# ---------- 5) Overloads + Literal narrowing + TypeGuard ----------

@overload
def parse_mode(value: str, /) -> Literal["fast", "slow"]: ...
@overload
def parse_mode(value: None, /) -> None: ...

def parse_mode(value: str | None, /) -> Literal["fast", "slow"] | None:
    """Overloaded function with Literal return."""
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("fast", "slow"):
        return v  # type: ignore[return-value]
    raise ValueError(f"bad mode: {value!r}")


def is_decimal_string(x: str) -> TypeGuard[str]:
    """TypeGuard test (not super meaningful but useful for tools)."""
    try:
        Decimal(x)
        return True
    except Exception:
        return False


# ---------- 6) Weird defaults + sentinels + Never ----------

def default_weirdness(
    x: int,
    y: Any = Sentinel,
    /,
    z: Callable[[], int] = int,
    *,
    when: datetime = datetime(1970, 1, 1),
    fmt: str = "%Y-%m-%dT%H:%M:%S",
    strict: bool = False,
) -> int | Never:
    """
    Args:
      x: required
      y: default is a sentinel object (Final at module scope).
      z: default is a callable (int).
      when: fixed datetime default (repr stable-ish).
      fmt: format string.
      strict: if True, invalid inputs raise (Never return).

    Returns:
      int or Never
    """
    if strict and y is Sentinel:
        raise ValueError("strict requires y")
    return z() + x


# ---------- 7) Async + complex Awaitable/Coroutine ----------

async def async_stress(
    coro: Coroutine[Any, Any, JSONValue],
    /,
    *,
    timeout: float | None = None,
    on_done: Callable[[JSONValue], Awaitable[None]] | None = None,
) -> JSONValue:
    """
    Async function with Coroutine + Awaitable.

    Parameters:
        coro: a coroutine yielding JSONValue.
        timeout: optional (not used here).
        on_done: async callback.
    """
    result = await coro
    if on_done:
        await on_done(result)
    return result


# ---------- 8) Protocol + structural typing + kwargs-only TypedDict ----------

class Request(Protocol):
    method: str
    url: str
    headers: Mapping[str, str]


def request_handler(
    req: Request,
    /,
    payload: Payload,
    *,
    cfg: Cfg = Cfg(),
    closeables: Sequence[SupportsClose] = (),
    extra: SupportsGetItem[JSONValue] | None = None,
    **meta: Unpack[Meta],
) -> dict[str, JSONValue]:
    """
    Exercises Protocol parameters, TypedDict payload, dataclass default, Unpack[TypedDict] in kwargs.

    - payload is a TypedDict with Required/NotRequired
    - **meta is Unpack[Meta] (TypedDict expansion)
    """
    for c in closeables:
        c.close()
    out: dict[str, JSONValue] = {"method": req.method, "url": req.url, "host": cfg.host}
    out["trace_id"] = meta.get("trace_id", None)
    out["data"] = payload["data"]
    if extra is not None:
        out["extra_val"] = extra["k"]  # structural __getitem__
    return out


from src.endpoint.endpoints import NativeEndpoint

for func in (signature_stress, recursive_tree_op, wrap_with_prefix, tuple_pack_unpack, parse_mode, is_decimal_string,
             default_weirdness, async_stress, request_handler):
    ep = NativeEndpoint.from_function(func, "")
    print(ep._help_str)
    for arg in ep._arguments:
        print(arg)
