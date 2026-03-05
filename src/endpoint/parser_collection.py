from dataclasses import dataclass, replace as dc_replace
import warnings
import argparse
import abc
import ast

# Internal import
from .native_parser import Parser, Argument
from .functional import NoDefault

# Standard typing imports for aps
import typing_extensions as _te
import collections.abc as _a
import typing as _ty

if _ty.TYPE_CHECKING:
    import _typeshed as _tsh
import types as _ts

__all__ = ["ArgumentParsingError", "LightParser", "TokenStreamParser", "ArgparseParser", "StrictDFAParser",
           "FastParser", "TinyParser"]


@dataclass
class ArgumentParsingError(Exception):
    """Parser-collection argument parsing error.

    :param message: Human-readable error description.
    :param idx: Optional token index where the error occurred.
    :param endpoint_path: Optional endpoint identifier.
    :return: None.
    """
    message: str
    idx: int | None = None
    endpoint_path: str | None = None

    def __str__(self) -> str:
        """Render compact diagnostic string.

        :return: Error message with optional index and endpoint information.
        """
        loc = f" (idx={self.idx})" if self.idx is not None else ""
        ep = f" [{self.endpoint_path}]" if self.endpoint_path else ""
        return f"{self.message}{loc}{ep}"


class Type1Parser(Parser, metaclass=abc.ABCMeta):
    """Shared parser base with conversion/default helpers."""

    @staticmethod
    def _validate_choices(value: _ty.Any, arg: Argument) -> None:
        """Validate parsed value against configured ``choices``.

        :param value: Parsed value.
        :param arg: Argument metadata.
        :return: None.
        :raises ArgumentParsingError: If value is not in ``arg.choices``.
        """
        if arg.choices:
            # arg.choices are typed values; compare directly
            if value not in arg.choices:
                raise ArgumentParsingError(
                    f"Invalid value for '{arg.name}': {value!r}. Choices: {arg.choices!r}"
                )

    @staticmethod
    def _apply_defaults_and_required(parsed: dict[str, _ty.Any], arguments: list[Argument]) -> None:
        """Apply defaults and enforce required arguments.

        :param parsed: Parsed output mapping to mutate.
        :param arguments: Declared arguments.
        :return: None.
        :raises ArgumentParsingError: If a required argument is missing.
        """
        for a in arguments:
            if a.name in parsed:
                continue
            if not isinstance(a.default, NoDefault):
                parsed[a.name] = a.default
            elif a.required:
                raise ArgumentParsingError(f"Missing required argument: '{a.name}'")

    @classmethod
    def _coerce_from_type(cls, value: str, arg: Argument) -> _ty.Any:
        """Best-effort conversion based on ``arg.type``.

        Supported patterns include:

        - boolean spellings (``true/false``, ``1/0``, etc.)
        - ``typing.Literal`` values
        - ``typing.Optional`` / ``typing.Union`` branches
        - plain and parametrized collection types
        - constructor-based scalar conversions (``int``, ``float``, ``str``, ...)

        :param value: Raw string token value.
        :param arg: Argument metadata containing target type.
        :return: Coerced typed value.
        :raises ArgumentParsingError: If coercion fails for all supported paths.
        """
        t = arg.type

        # bool (accept typical CLI spellings)
        if t is bool:
            v = value.strip().lower()
            if v in {"1", "true", "t", "yes", "y", "on"}:
                return True
            if v in {"0", "false", "f", "no", "n", "off"}:
                return False
            raise ArgumentParsingError(f"Invalid boolean for '{arg.name}': {value}")

        origin = _ty.get_origin(t)
        args = _ty.get_args(t)

        # Literal
        if origin is _ty.Literal:
            # try to match by converting to the literal members' types first
            choices = list(args)
            # exact string match first
            for c in choices:
                if str(c) == value:
                    return c
            # then try typed conversion
            for c in choices:
                try:
                    if isinstance(c, bool):
                        return cls._coerce_from_type(value, dc_replace(arg, type=bool))  # type: ignore[arg-type]
                    return type(c)(value)
                except Exception:
                    continue
            raise ArgumentParsingError(f"Value '{value}' not in Literal choices for '{arg.name}'")

        # Optional / Union
        if origin is _ty.Union and args:
            last_err: Exception | None = None
            for option_t in args:
                if option_t is type(None):  # noqa: E721
                    if value.strip().lower() in {"none", "null"}:
                        return None
                    continue
                try:
                    # recurse with a lightweight "shadow arg"
                    shadow = dc_replace(arg, type=option_t)  # type: ignore[arg-type]
                    return cls._coerce_from_type(value, shadow)
                except Exception as e:
                    last_err = e
            raise ArgumentParsingError(
                f"Could not coerce '{value}' into any Union option for '{arg.name}'"
            ) from last_err

        # collections (single-token forms: "a,b,c" or "a b c" not possible as one token)
        if t in (list, tuple, set):
            parts = [p for p in value.split(",") if p != ""]
            return t(parts)  # type: ignore[misc]

        # typing collections like list[int], tuple[str], set[float]
        if origin in (list, tuple, set) and args:
            elem_t = args[0] if origin is not tuple else (args[0] if len(args) == 1 else args)
            parts = [p for p in value.split(",") if p != ""]
            if origin is tuple and isinstance(elem_t, tuple):
                # tuple[T1,T2,...] exact arity
                if len(parts) != len(elem_t):
                    raise ArgumentParsingError(
                        f"Expected {len(elem_t)} values for '{arg.name}', got {len(parts)}"
                    )
                out = []
                for p, et in zip(parts, elem_t, strict=True):
                    shadow = dc_replace(arg, type=et)  # type: ignore[arg-type]
                    out.append(cls._coerce_from_type(p, shadow))
                return tuple(out)
            else:
                # list[T]/set[T]/tuple[T,...]
                shadow_elem = dc_replace(arg, type=elem_t)  # type: ignore[arg-type]
                coerced = [cls._coerce_from_type(p, shadow_elem) for p in parts]
                return origin(coerced)  # type: ignore[misc]

        # fallback: constructor
        try:
            return t(value)
        except Exception as e:
            raise ArgumentParsingError(f"Could not convert '{value}' to {t} for '{arg.name}'") from e


class LightParser(Type1Parser):
    """Simple option/positional parser with lightweight coercion."""

    def __init__(self, enabled_flags: dict[str, _ty.Any]) -> None:
        """Initialize parser flags.

        :param enabled_flags: Runtime parser flags.
        :return: None.
        """
        self._enabled_flags = enabled_flags
        self.smart_typing: bool = enabled_flags.get("smart_typing", True)
        self.allow_combined_short: bool = enabled_flags.get("allow_combined_short", True)

    def list_known_flags(self) -> dict[str, type[_ty.Any]]:
        """Return supported configuration flags."""
        return {
            "smart_typing": bool,
            "allow_combined_short": bool,
        }

    def explain_flag(self, flag_name: str) -> str:
        """Explain one parser flag.

        :param flag_name: Flag name.
        :return: Description text.
        :raises ValueError: If flag is unknown.
        """
        explanations: dict[str, str] = {
            "smart_typing": (
                "Enable best-effort type coercion for option values. "
                "When disabled, conversion behavior is stricter."
            ),
            "allow_combined_short": (
                "Allow combined short boolean flags such as '-abc' "
                "(equivalent to '-a -b -c')."
            ),
        }
        key = flag_name.strip()
        if key not in explanations:
            raise ValueError(f"Unknown flag '{flag_name}'. Known flags: {', '.join(explanations)}")
        return explanations[key]

    def parse_args(self, args: list[str], arguments: list[Argument], endpoint_path: str
                   ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """Parse tokens using long/short options and positionals.

        :param args: Raw CLI tokens.
        :param arguments: Declared argument metadata.
        :param endpoint_path: Endpoint identifier for diagnostics.
        :return: Parsed ``(positionals, kwargs)``.
        """
        name_map = {a.name: a for a in arguments}
        for a in arguments:
            for alt in a.alternative_names:
                name_map[alt] = a
            if a.letter:
                name_map[a.letter] = a

        positional = [a for a in arguments if a.type is not bool]
        pos_i = 0

        out: dict[str, _ty.Any] = {}
        i = 0

        while i < len(args):
            tok = args[i]

            # --long
            if tok.startswith("--"):
                key, _, val = tok[2:].partition("=")
                arg = name_map.get(key)
                if not arg:
                    raise ArgumentParsingError(f"Unknown argument {key}", i)

                if arg.type is bool:
                    out[arg.name] = True if not val else self._coerce_from_type(val, arg)
                else:
                    if not val:
                        i += 1
                        val = args[i]
                    out[arg.name] = self._coerce_from_type(val, arg)

                i += 1
                continue

            # -x / -abc
            if tok.startswith("-") and tok != "-":
                body = tok[1:]

                if self.allow_combined_short and len(body) > 1:
                    for c in body:
                        arg = name_map.get(c)
                        if not arg or arg.type is not bool:
                            raise ArgumentParsingError(f"Invalid short flag {c}", i)
                        out[arg.name] = True
                    i += 1
                    continue

                arg = name_map.get(body)
                if not arg:
                    raise ArgumentParsingError(f"Unknown argument {body}", i)

                if arg.type is bool:
                    out[arg.name] = True
                else:
                    i += 1
                    out[arg.name] = self._coerce_from_type(args[i], arg)

                i += 1
                continue

            # positional
            if pos_i >= len(positional):
                raise ArgumentParsingError("Too many positional arguments", i)

            arg = positional[pos_i]
            pos_i += 1
            out[arg.name] = self._coerce_from_type(tok, arg)
            i += 1

        self._apply_defaults_and_required(out, arguments)
        return list(), out


class TokenStreamParser(Type1Parser):
    """Streaming parser supporting option/positional interleaving.

    Features include:

    - ``--`` end-of-options separator support.
    - Interleaved positionals and options when enabled.
    - Repeated collection merging:
      ``--tags=a --tags=b`` -> ``tags=['a', 'b']``.
    - Last-value-wins behavior for non-collection parameters.
    """

    def __init__(self, enabled_flags: dict[str, _ty.Any]) -> None:
        """Initialize stream parser flags.

        :param enabled_flags: Runtime parser flags.
        :return: None.
        """
        self._enabled_flags = enabled_flags
        self.repeatable = enabled_flags.get("repeatable_collections", True)
        self.interleaved = enabled_flags.get("interleaved_positionals", True)

    def list_known_flags(self) -> dict[str, type[_ty.Any]]:
        """Return supported configuration flags."""
        return {
            "repeatable_collections": bool,
            "interleaved_positionals": bool,
        }

    def explain_flag(self, flag_name: str) -> str:
        """Explain one parser flag.

        :param flag_name: Flag name.
        :return: Description text.
        :raises ValueError: If flag is unknown.
        """
        explanations: dict[str, str] = {
            "repeatable_collections": (
                "Allow repeated assignments for collection arguments. "
                "For example, '--tags=a --tags=b' merges into a single value."
            ),
            "interleaved_positionals": (
                "Allow positional arguments to appear interleaved with options."
            ),
        }
        key = flag_name.strip()
        if key not in explanations:
            raise ValueError(f"Unknown flag '{flag_name}'. Known flags: {', '.join(explanations)}")
        return explanations[key]

    @staticmethod
    def _build_name_index(arguments: list[Argument]) -> dict[str, Argument]:
        """Build lookup table from accepted names to ``Argument``.

        :param arguments: Declared arguments.
        :return: Name-to-argument mapping.
        """
        idx: dict[str, Argument] = {}
        for a in arguments:
            idx[a.name] = a
            for alt in a.alternative_names:
                idx[alt] = a
            if a.letter:
                idx[a.letter] = a
        return idx

    def parse_args(
        self, args: list[str], arguments: list[Argument], endpoint_path: str
    ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """Parse tokens with streaming semantics.

        :param args: Raw CLI tokens.
        :param arguments: Declared argument metadata.
        :param endpoint_path: Endpoint identifier for diagnostics.
        :return: Parsed ``(positionals, kwargs)``.
        """
        name_index = self._build_name_index(arguments)

        positional = [a for a in arguments if a.type is not bool]
        pos_i = 0

        parsed: dict[str, _ty.Any] = {}
        i = 0
        options_mode = True

        def is_collection_type(t: _ty.Any) -> bool:
            origin = _ty.get_origin(t)
            return t in (list, set, tuple) or origin in (list, set, tuple)

        def merge_value(a: Argument, v: _ty.Any) -> None:
            # If repeatable is off, always "last value wins"
            if not self.repeatable or not is_collection_type(a.type):
                parsed[a.name] = v
                return

            existing = parsed.get(a.name)
            if existing is None:
                # initialize with the right container shape
                if a.type in (set,) or _ty.get_origin(a.type) is set:
                    parsed[a.name] = set(v) if isinstance(v, (list, tuple, set)) else {v}
                elif a.type in (tuple,) or _ty.get_origin(a.type) is tuple:
                    parsed[a.name] = tuple(v) if isinstance(v, (list, tuple)) else (v,)
                else:
                    parsed[a.name] = list(v) if isinstance(v, (list, tuple, set)) else [v]
                return

            # merge into existing
            if isinstance(existing, set):
                existing.update(v if isinstance(v, (list, tuple, set)) else [v])
            elif isinstance(existing, tuple):
                parsed[a.name] = existing + (tuple(v) if isinstance(v, (list, tuple)) else (v,))
            else:  # list-like
                existing.extend(v if isinstance(v, (list, tuple, set)) else [v])

        while i < len(args):
            tok = args[i]

            # explicit end-of-options
            if options_mode and tok == "--":
                options_mode = False
                i += 1
                continue

            # long option
            if options_mode and tok.startswith("--") and tok != "--":
                keyval = tok[2:]
                key, eq, maybe = keyval.partition("=")

                if key not in name_index:
                    raise ArgumentParsingError(f"Unknown argument: --{key}", i)
                a = name_index[key]

                if a.type is bool:
                    v = True if not eq else self._coerce_from_type(maybe, a)
                    self._validate_choices(v, a)
                    merge_value(a, v)
                    i += 1
                    continue

                # needs a value
                if eq:
                    raw = maybe
                else:
                    if i + 1 >= len(args):
                        raise ArgumentParsingError(f"No value provided for '--{key}'", i)
                    i += 1
                    raw = args[i]

                v = self._coerce_from_type(raw, a)
                self._validate_choices(v, a)
                merge_value(a, v)
                i += 1
                continue

            # short option(s)
            if options_mode and tok.startswith("-") and tok != "-":
                body = tok[1:]
                short, eq, maybe = body.partition("=")

                # combined bools: -abc
                if len(short) > 1 and not eq:
                    all_bool = all(ch in name_index and name_index[ch].type is bool for ch in short)
                    if all_bool:
                        for ch in short:
                            a = name_index[ch]
                            self._validate_choices(True, a)
                            merge_value(a, True)
                        i += 1
                        continue

                if short not in name_index:
                    raise ArgumentParsingError(f"Unknown argument: -{short}", i)
                a = name_index[short]

                if a.type is bool:
                    v = True if not eq else self._coerce_from_type(maybe, a)
                    self._validate_choices(v, a)
                    merge_value(a, v)
                    i += 1
                    continue

                # needs a value
                if eq:
                    raw = maybe
                else:
                    if i + 1 >= len(args):
                        raise ArgumentParsingError(f"No value provided for '-{short}'", i)
                    i += 1
                    raw = args[i]

                v = self._coerce_from_type(raw, a)
                self._validate_choices(v, a)
                merge_value(a, v)
                i += 1
                continue

            # positional token (or after `--`)
            if pos_i >= len(positional):
                raise ArgumentParsingError(f"Unexpected positional argument: {tok}", i)

            # If interleaving is disabled, first positional ends option parsing (like many CLIs)
            if options_mode and not self.interleaved:
                options_mode = False

            a = positional[pos_i]
            pos_i += 1
            v = self._coerce_from_type(tok, a)
            self._validate_choices(v, a)
            merge_value(a, v)
            i += 1

        self._apply_defaults_and_required(parsed, arguments)
        return list(), parsed


# TODO: Remove? Now we have a proper endpoint for it
@_te.deprecated("ArgparseParser is deprecated. Please use ArgparseEndpoint instead.")
class ArgparseParser(Type1Parser):
    """Compatibility parser backed by :mod:`argparse`.

    .. deprecated:: ArgparseParser is deprecated. Use ``ArgparseEndpoint``.

    Supported behavior includes:

    - ``--name value`` and ``--name=value``
    - short option letters when configured
    - choices/default/required enforcement
    - boolean presence flags with optional explicit values
    """

    def __init__(self, enabled_flags: dict[str, _ty.Any]) -> None:
        """Initialize argparse-backed parser.

        :param enabled_flags: Runtime parser flags.
        :return: None.
        """
        self._enabled_flags = enabled_flags
        self.allow_abbrev = enabled_flags.get("allow_abbrev", False)

    @_te.deprecated("ArgparseParser is deprecated. Please use ArgparseEndpoint instead.")
    def list_known_flags(self) -> dict[str, type[_ty.Any]]:
        """Return supported configuration flags."""
        warnings.warn("ArgparseParser is deprecated. Please use ArgparseEndpoint instead.", stacklevel=2)
        return {
            "allow_abbrev": bool,
        }

    @_te.deprecated("ArgparseParser is deprecated. Please use ArgparseEndpoint instead.")
    def explain_flag(self, flag_name: str) -> str:
        """Explain one parser flag.

        :param flag_name: Flag name.
        :return: Description text.
        :raises ValueError: If flag is unknown.
        """
        warnings.warn("ArgparseParser is deprecated. Please use ArgparseEndpoint instead.", stacklevel=2)
        explanations: dict[str, str] = {
            "allow_abbrev": (
                "Allow argparse long-option abbreviation. "
                "If disabled, long option names must match exactly."
            ),
        }
        key = flag_name.strip()
        if key not in explanations:
            raise ValueError(f"Unknown flag '{flag_name}'. Known flags: {', '.join(explanations)}")
        return explanations[key]

    @staticmethod
    def _accepts_argument(parser_flags: dict[str, _ty.Any], endpoint_path: str, name: str) -> bool:
        """Check whether one option spelling is enabled.

        ``enabled_flags`` supports both global and per-endpoint forms:

        - ``{"--foo": True}``
        - ``{"<endpoint_path>": {"--foo": True}}``

        :param parser_flags: Parser flag dictionary.
        :param endpoint_path: Endpoint identifier.
        :param name: Option spelling to evaluate.
        :return: ``True`` when option is accepted.
        """
        if name in parser_flags:
            return bool(parser_flags[name])
        per = parser_flags.get(endpoint_path)
        if isinstance(per, dict):
            return bool(per.get(name, False))
        # default: allow everything unless explicitly disabled
        return True

    @_te.deprecated("ArgparseParser is deprecated. Please use ArgparseEndpoint instead.")
    def parse_args(
        self, args: list[str], arguments: list[Argument], endpoint_path: str
    ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """Parse tokens using stdlib argparse.

        :param args: Raw CLI tokens.
        :param arguments: Declared argument metadata.
        :param endpoint_path: Endpoint identifier for diagnostics.
        :return: Parsed ``(positionals, kwargs)``.
        """
        warnings.warn("ArgparseParser is deprecated. Please use ArgparseEndpoint instead.", stacklevel=2)
        p = argparse.ArgumentParser(allow_abbrev=self.allow_abbrev, add_help=False)

        # We map all accepted spellings to the same dest (primary name).
        for a in arguments:
            long_opts = [f"--{a.name}", *[f"--{x}" for x in a.alternative_names]]
            short_opts: list[str] = [f"-{a.letter}"] if a.letter else []

            # filter enabled flags (if user disables a spelling, remove it)
            opts = [*short_opts, *long_opts]
            opts = [o for o in opts if self._accepts_argument(self._enabled_flags, endpoint_path, o)]
            if not opts:
                continue

            kwargs: dict[str, _ty.Any] = dict(dest=a.name, help=a.help or None, metavar=a.metavar or None)

            if a.type is bool:
                # Support: --flag (True) AND --flag=false
                # Use nargs='?' with const=True and custom type conversion.
                kwargs.update(
                    nargs="?",
                    const=True,
                    default=(None if isinstance(a.default, NoDefault) else a.default),
                    type=lambda s, _a=a: self._coerce_from_type(s, _a),
                )
            else:
                kwargs.update(
                    required=a.required and isinstance(a.default, NoDefault),
                    default=(argparse.SUPPRESS if isinstance(a.default, NoDefault) else a.default),
                    type=lambda s, _a=a: self._coerce_from_type(s, _a),
                )
                if a.choices:
                    kwargs["choices"] = a.choices

            p.add_argument(*opts, **kwargs)

        try:
            ns, extra = p.parse_known_args(args)
        except SystemExit as e:
            # argparse uses SystemExit on errors; translate to our error.
            raise ArgumentParsingError("argparse failed to parse arguments") from e

        if extra:
            # treat any remaining tokens as unexpected (keeps behavior close to native_light)
            raise ArgumentParsingError(f"Unexpected arguments: {extra!r}")

        parsed = vars(ns)

        # argparse with SUPPRESS won't include missing defaults; we enforce required + defaults here too
        self._apply_defaults_and_required(parsed, arguments)

        # choices already validated by argparse for non-bool; validate bool choices if any (rare)
        for a in arguments:
            if a.name in parsed:
                self._validate_choices(parsed[a.name], a)

        return list(), parsed

STRICT_DFA_FLAG_TYPES: dict[str, type[_ty.Any]] = {
    # Grammar control (DFA-friendly)
    "DFA_REQUIRE_INLINE_ASSIGNMENT": bool,   # True => '--k=v' only; False => allow '--k v'
    "DFA_ASSIGN_TOKENS": str,                # tokens allowed between key and value, e.g. "=:" means '=' or ':'

    # Positional policy
    "DFA_ALLOW_POSITIONALS": bool,           # allow positionals at all
    "DFA_POSITIONALS_AFTER_OPTIONS": bool,   # once a positional is seen, no more options

    # Value decoding behavior
    "DFA_TEXT_ENCODING": str,                # encoding used when converting to bytes (or decoding escapes if you do)
    "DFA_BOOL_PRESENT_VALUE": bool,          # value to assign when a bool flag is present (default True)
    "DFA_BOOL_TOGGLE_IF_DEFAULT": bool,      # if True and default is bool, presence toggles it
}


STRICT_DFA_DEFAULT_FLAGS: dict[str, _ty.Any] = {
    "DFA_REQUIRE_INLINE_ASSIGNMENT": True,
    "DFA_ASSIGN_TOKENS": "=:",
    "DFA_ALLOW_POSITIONALS": True,
    "DFA_POSITIONALS_AFTER_OPTIONS": True,
    "DFA_TEXT_ENCODING": "utf-8",
    "DFA_BOOL_PRESENT_VALUE": True,
    "DFA_BOOL_TOGGLE_IF_DEFAULT": False,
}


class StrictDFAParser(Parser):
    """Deterministic finite-state parser with strict option grammar."""

    def __init__(self, enabled_flags: dict[str, _ty.Any]) -> None:
        """Initialize DFA parser from merged defaults and overrides.

        :param enabled_flags: Runtime parser flags.
        :return: None.
        """
        flags = {**STRICT_DFA_DEFAULT_FLAGS, **enabled_flags}

        self._require_inline: bool = flags["DFA_REQUIRE_INLINE_ASSIGNMENT"]
        self._assign_tokens: str = flags["DFA_ASSIGN_TOKENS"]

        self._allow_positionals: bool = flags["DFA_ALLOW_POSITIONALS"]
        self._positionals_after_options: bool = flags["DFA_POSITIONALS_AFTER_OPTIONS"]

        self._text_encoding: str = flags["DFA_TEXT_ENCODING"]
        self._bool_present_value: bool = flags["DFA_BOOL_PRESENT_VALUE"]
        self._bool_toggle_if_default: bool = flags["DFA_BOOL_TOGGLE_IF_DEFAULT"]

    def list_known_flags(self) -> dict[str, type[_ty.Any]]:
        """Return supported configuration flags."""
        return dict(STRICT_DFA_FLAG_TYPES)

    def explain_flag(self, flag_name: str) -> str:
        """Explain one parser flag.

        :param flag_name: Flag name.
        :return: Description text.
        :raises ValueError: If flag is unknown.
        """
        explanations: dict[str, str] = {
            "DFA_REQUIRE_INLINE_ASSIGNMENT": "Require inline '--k=v' assignment for valued options.",
            "DFA_ASSIGN_TOKENS": "Characters recognized as assignment tokens when splitting key/value.",
            "DFA_ALLOW_POSITIONALS": "Allow positional arguments in addition to options.",
            "DFA_POSITIONALS_AFTER_OPTIONS": "Reject options after positional parsing has started.",
            "DFA_TEXT_ENCODING": "Encoding used when converting text to bytes.",
            "DFA_BOOL_PRESENT_VALUE": "Value assigned when a boolean flag is present.",
            "DFA_BOOL_TOGGLE_IF_DEFAULT": "Toggle boolean defaults on presence when enabled.",
        }
        key = flag_name.strip()
        if key not in explanations:
            raise ValueError(f"Unknown flag '{flag_name}'. Known flags: {', '.join(explanations)}")
        return explanations[key]

    def _split_assignment(self, s: str) -> tuple[str, str] | None:
        """Split ``key<assign>value`` using configured assignment tokens.

        :param s: Raw option body.
        :return: ``(key, value)`` or ``None`` when no assignment token exists.
        """
        for t in self._assign_tokens:
            k, sep, v = s.partition(t)
            if sep:
                return k, v
        return None

    def _coerce_basic(self, value: str, target: type[_ty.Any]) -> _ty.Any:
        """Coerce raw text into a basic target type.

        :param value: Raw token text.
        :param target: Destination type.
        :return: Parsed value.
        :raises ValueError: If conversion fails.
        """
        if target is str:
            return value
        if target is bool:
            # used only if you ever allow explicit bool values; otherwise bools are presence-based
            v = value.strip().lower()
            if v in {"1", "true", "t", "yes", "y", "on"}:
                return True
            if v in {"0", "false", "f", "no", "n", "off"}:
                return False
            raise ValueError(f"Invalid boolean literal: {value!r}")
        if target is int:
            return int(value)
        if target is float:
            return float(value)
        if target is complex:
            return complex(value.replace(" ", ""))
        if target is bytes:
            s = value.strip()
            if s.startswith(("b'", 'b"', "B'", 'B"')):
                lit = ast.literal_eval(s)
                if isinstance(lit, (bytes, bytearray)):
                    return bytes(lit)
                raise ValueError(f"Not a bytes literal: {value!r}")
            return value.encode(self._text_encoding)
        return target(value)

    @staticmethod
    def _name_to_arg(arguments: list[Argument]) -> dict[str, Argument]:
        """Build lookup table from long/alt/short names to arguments."""
        m: dict[str, Argument] = {}
        for a in arguments:
            m[a.name] = a
            for alt in a.alternative_names:
                m[alt.lstrip("-")] = a
            if a.letter:
                m[a.letter] = a
        return m

    @staticmethod
    def _finalize_defaults(parsed: dict[str, _ty.Any], arguments: list[Argument]) -> None:
        """Apply defaults and enforce required arguments."""
        for a in arguments:
            if a.name in parsed:
                continue
            if not isinstance(a.default, NoDefault):
                parsed[a.name] = a.default
            elif a.required:
                raise ArgumentParsingError(f"Missing required argument: {a.name}")

    def parse_args(self, args: list[str], arguments: list[Argument], endpoint_path: str
                   ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """Parse tokens with strict DFA-style rules.

        :param args: Raw CLI tokens.
        :param arguments: Declared argument metadata.
        :param endpoint_path: Endpoint identifier for diagnostics.
        :return: Parsed ``(positionals, kwargs)``.
        """
        name_map = self._name_to_arg(arguments)
        parsed: dict[str, _ty.Any] = {}

        def set_bool(arg: Argument) -> None:
            if self._bool_toggle_if_default and not isinstance(arg.default, NoDefault) and isinstance(arg.default, bool):
                parsed[arg.name] = not arg.default
            else:
                parsed[arg.name] = self._bool_present_value

        positional_list = [a for a in arguments if a.type is not bool]
        seen_positional = False

        for idx, tok in enumerate(args):
            # deterministic rule (optional): after positionals begin, options forbidden
            if seen_positional and self._positionals_after_options and (tok.startswith("-") and tok != "-"):
                raise ArgumentParsingError("Options not allowed after positional arguments", idx=idx, endpoint_path=endpoint_path)

            if tok.startswith("--"):
                raw = tok[2:]
                kv = self._split_assignment(raw)

                if kv is None:
                    # No assignment present
                    arg = name_map.get(raw)
                    if arg and arg.type is bool:
                        set_bool(arg)
                        continue
                    if self._require_inline:
                        raise ArgumentParsingError(
                            f"Expected inline assignment for --{raw} (use one of {list(self._assign_tokens)!r})",
                            idx=idx,
                            endpoint_path=endpoint_path,
                        )
                    # If you ever allow '--k v', you'd consume next token here (not shown to keep DFA strict).
                    raise ArgumentParsingError(f"Missing value for --{raw}", idx=idx, endpoint_path=endpoint_path)

                key, val = kv
                arg = name_map.get(key)
                if arg is None:
                    raise ArgumentParsingError(f"Unknown argument: {key}", idx=idx, endpoint_path=endpoint_path)
                if arg.type is bool:
                    raise ArgumentParsingError(f"Boolean flag --{key} must not take a value", idx=idx, endpoint_path=endpoint_path)

                try:
                    v = self._coerce_basic(val, arg.type)
                    if arg.choices and v not in arg.choices:
                        raise ValueError(f"{v!r} not in {arg.choices!r}")
                except Exception as e:
                    raise ArgumentParsingError(f"Failed to parse {arg.name}: {e}", idx=idx, endpoint_path=endpoint_path)

                parsed[arg.name] = v
                continue

            if tok.startswith("-") and tok != "-":
                raw = tok[1:]
                kv = self._split_assignment(raw)

                if kv is None:
                    arg = name_map.get(raw)
                    if arg is None:
                        raise ArgumentParsingError(f"Unknown short option: -{raw}", idx=idx, endpoint_path=endpoint_path)
                    if arg.type is not bool:
                        raise ArgumentParsingError(f"Option -{raw} requires assignment (e.g. -{raw}=...)", idx=idx, endpoint_path=endpoint_path)
                    set_bool(arg)
                    continue

                key, val = kv
                arg = name_map.get(key)
                if arg is None:
                    raise ArgumentParsingError(f"Unknown short option: -{key}", idx=idx, endpoint_path=endpoint_path)
                if arg.type is bool:
                    raise ArgumentParsingError(f"Boolean flag -{key} must not take a value", idx=idx, endpoint_path=endpoint_path)

                try:
                    v = self._coerce_basic(val, arg.type)
                    if arg.choices and v not in arg.choices:
                        raise ValueError(f"{v!r} not in {arg.choices!r}")
                except Exception as e:
                    raise ArgumentParsingError(f"Failed to parse {arg.name}: {e}", idx=idx, endpoint_path=endpoint_path)

                parsed[arg.name] = v
                continue

            # positional
            if not self._allow_positionals:
                raise ArgumentParsingError(f"Positional args disabled; got {tok!r}", idx=idx, endpoint_path=endpoint_path)

            seen_positional = True
            a = next((x for x in positional_list if x.name not in parsed), None)
            if a is None:
                raise ArgumentParsingError(f"Too many positional args; unexpected {tok!r}", idx=idx, endpoint_path=endpoint_path)

            try:
                v = self._coerce_basic(tok, a.type)
                if a.choices and v not in a.choices:
                    raise ValueError(f"{v!r} not in {a.choices!r}")
            except Exception as e:
                raise ArgumentParsingError(f"Failed to parse {a.name}: {e}", idx=idx, endpoint_path=endpoint_path)

            parsed[a.name] = v

        self._finalize_defaults(parsed, arguments)
        return list(), parsed


FAST_FLAG_TYPES: dict[str, type[_ty.Any]] = {
    "FAST_ALLOW_POSITIONALS": bool,
    "FAST_ASSIGN_CHAR": str,        # single char, default '='
    "FAST_BOOL_PRESENT": bool,      # value assigned to bool flags
}

FAST_FLAG_DEFAULTS = {
    "FAST_ALLOW_POSITIONALS": False,
    "FAST_ASSIGN_CHAR": "=",
    "FAST_BOOL_PRESENT": True,
}

class FastParser(Parser):
    """High-throughput parser with minimal branching and strict syntax.

    Grammar:

    - ``--name=value``
    - ``-x=value``
    - ``--flag`` / ``-f`` for booleans
    - positionals in declared order (when enabled)

    Design focus:

    - one-pass processing
    - low branching overhead
    - minimal recovery logic
    """

    def __init__(self, enabled_flags: dict[str, _ty.Any]) -> None:
        """Initialize fast parser.

        :param enabled_flags: Runtime parser flags.
        :return: None.
        """
        f = {**FAST_FLAG_DEFAULTS, **enabled_flags}

        self._allow_positional: bool = f["FAST_ALLOW_POSITIONALS"]
        self._assign_char: str = f["FAST_ASSIGN_CHAR"]
        self._bool_present: bool = f["FAST_BOOL_PRESENT"]

        if len(self._assign_char) != 1:
            raise ValueError("FAST_ASSIGN_CHAR must be a single character")

    def list_known_flags(self) -> dict[str, type[_ty.Any]]:
        """Return supported configuration flags."""
        return dict(FAST_FLAG_TYPES)

    def explain_flag(self, flag_name: str) -> str:
        """Explain one parser flag.

        :param flag_name: Flag name.
        :return: Description text.
        :raises ValueError: If flag is unknown.
        """
        explanations: dict[str, str] = {
            "FAST_ALLOW_POSITIONALS": "Allow positional arguments.",
            "FAST_ASSIGN_CHAR": "Single character used for inline option assignment.",
            "FAST_BOOL_PRESENT": "Value assigned when a boolean flag is present.",
        }
        key = flag_name.strip()
        if key not in explanations:
            raise ValueError(f"Unknown flag '{flag_name}'. Known flags: {', '.join(explanations)}")
        return explanations[key]

    def parse_args(
        self,
        args: list[str],
        arguments: list[Argument],
        endpoint_path: str,
    ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """Parse tokens using the optimized fast-path grammar.

        :param args: Raw CLI tokens.
        :param arguments: Declared argument metadata.
        :param endpoint_path: Endpoint identifier for diagnostics.
        :return: Parsed ``(positionals, kwargs)``.
        """

        # Precompute name → Argument
        name_map = {}
        positionals = []

        for a in arguments:
            name_map[a.name] = a
            if a.letter:
                name_map[a.letter] = a
            for alt in a.alternative_names:
                name_map[alt.lstrip("-")] = a
            if a.type is not bool:
                positionals.append(a)

        parsed: dict[str, _ty.Any] = {}
        pos_i = 0
        assign = self._assign_char

        for tok in args:
            c0 = tok[0]

            # OPTION
            if c0 == "-" and tok != "-":
                if tok[1] == "-":
                    body = tok[2:]
                else:
                    body = tok[1:]

                eq = body.find(assign)

                # BOOL FLAG
                if eq < 0:
                    arg = name_map.get(body)
                    if arg is None or arg.type is not bool:
                        raise ArgumentParsingError(f"Unknown or non-bool flag: {tok}", None, endpoint_path)
                    parsed[arg.name] = self._bool_present
                    continue

                key = body[:eq]
                val = body[eq + 1 :]

                arg = name_map.get(key)
                if arg is None:
                    raise ArgumentParsingError(f"Unknown argument: {key}", None, endpoint_path)

                try:
                    parsed[arg.name] = arg.type(val)
                except Exception:
                    raise ArgumentParsingError(f"Bad value for {arg.name}: {val}", None, endpoint_path)

                continue

            # POSITIONAL
            if not self._allow_positional:
                raise ArgumentParsingError(f"Unexpected positional: {tok}", None, endpoint_path)

            if pos_i >= len(positionals):
                raise ArgumentParsingError(f"Too many positional args: {tok}", None, endpoint_path)

            arg = positionals[pos_i]
            pos_i += 1

            try:
                parsed[arg.name] = arg.type(tok)
            except Exception:
                raise ArgumentParsingError(f"Bad value for {arg.name}: {tok}", None, endpoint_path)

        # Defaults / required
        for a in arguments:
            if a.name not in parsed:
                if a.default is not NoDefault:
                    parsed[a.name] = a.default
                elif a.required:
                    raise ArgumentParsingError(f"Missing required arg: {a.name}", None, endpoint_path)

        return list(), parsed


class TinyParser(Parser):
    """Minimal parser variant with compact logic and no custom flags."""

    def __init__(self, enabled_flags: dict[str, _ty.Any]) -> None:
        """Initialize tiny parser.

        :param enabled_flags: Runtime parser flags (currently unused).
        :return: None.
        """
        pass

    def list_known_flags(self) -> dict[str, type[_ty.Any]]:
        """Return supported configuration flags."""
        return {}

    def explain_flag(self, flag_name: str) -> str:
        """Explain one parser flag.

        :param flag_name: Flag name.
        :raises ValueError: Always, because this parser has no flags.
        """
        raise ValueError(f"TinyParser exposes no configurable flags. Received '{flag_name}'.")  # We do not have any flags

    def parse_args(self, args: list[str], arguments: list[Argument], endpoint_path: str
                   ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """Parse tokens using tiny parser rules.

        :param args: Raw CLI tokens.
        :param arguments: Declared argument metadata.
        :param endpoint_path: Endpoint identifier for diagnostics.
        :return: Parsed ``(positionals, kwargs)``.
        """
        m = {}
        p = []
        d = {}
        r = []

        for a in arguments:
            m[a.name] = (a.name, a.type, a.type is bool)
            if a.letter:
                m[a.letter] = (a.name, a.type, a.type is bool)
            for alt in a.alternative_names:
                m[alt.lstrip("-")] = (a.name, a.type, a.type is bool)
            if a.type is not bool:
                p.append((a.name, a.type))
            if a.default is not NoDefault:
                d[a.name] = a.default
            elif a.required:
                r.append(a.name)

        out = {}
        i = 0

        for t in args:
            if t[0] == "-" and t != "-":
                b = t[2:] if t[1] == "-" else t[1:]
                if "=" in b:
                    k, v = b.split("=", 1)
                    n, c, _ = m[k]
                    out[n] = c(v)
                else:
                    n, _, _ = m[b]
                    out[n] = True
            else:
                n, c = p[i]
                i += 1
                out[n] = c(t)

        for k, v in d.items():
            if k not in out:
                out[k] = v

        for k in r:
            if k not in out:
                raise RuntimeError(f"missing {k}")

        return list(), out
