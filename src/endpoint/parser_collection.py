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

    def parse_args(self, args: list[str], arguments: "list[Argument]", endpoint_path: str,
                   endpoint_help_func: _a.Callable[[], str]) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
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
    """Feature-rich token-stream parser.

    This implementation focuses on broad CLI compatibility while remaining
    independent from the other parser implementations in this module.
    """

    IS_FULLY_FEATURED: bool = True

    def __init__(self, enabled_flags: dict[str, _ty.Any]) -> None:
        """Initialize stream parser flags.

        :param enabled_flags: Runtime parser flags.
        :return: None.
        """
        self._enabled_flags = enabled_flags
        self.repeatable: bool = enabled_flags.get("repeatable_collections", True)
        self.interleaved: bool = enabled_flags.get("interleaved_positionals", True)
        self.allow_combined_short: bool = enabled_flags.get("allow_combined_short", True)
        self.allow_inline_short_value: bool = enabled_flags.get("allow_inline_short_value", True)
        self.allow_long_equals: bool = enabled_flags.get("allow_long_equals", True)
        self.allow_short_equals: bool = enabled_flags.get("allow_short_equals", True)
        self.allow_values_starting_with_dash: bool = enabled_flags.get("allow_values_starting_with_dash", False)
        self.allow_negative_bool_forms: bool = enabled_flags.get("allow_negative_bool_forms", True)
        self.parse_literal_values: bool = enabled_flags.get("parse_literal_values", True)
        self.enforce_positional_only: bool = enabled_flags.get("enforce_positional_only", True)
        self.enforce_kwarg_only: bool = enabled_flags.get("enforce_kwarg_only", True)
        self.unknown_as_positional: bool = enabled_flags.get("unknown_as_positional", False)
        self.option_terminator: str = enabled_flags.get("option_terminator", "--")
        self.duplicate_policy: str = enabled_flags.get("duplicate_policy", "last")

    def list_known_flags(self) -> dict[str, type[_ty.Any]]:
        """Return supported configuration flags."""
        return {
            "repeatable_collections": bool,
            "interleaved_positionals": bool,
            "allow_combined_short": bool,
            "allow_inline_short_value": bool,
            "allow_long_equals": bool,
            "allow_short_equals": bool,
            "allow_values_starting_with_dash": bool,
            "allow_negative_bool_forms": bool,
            "parse_literal_values": bool,
            "enforce_positional_only": bool,
            "enforce_kwarg_only": bool,
            "unknown_as_positional": bool,
            "option_terminator": str,
            "duplicate_policy": str,
        }

    def explain_flag(self, flag_name: str) -> str:
        """Explain one parser flag.

        :param flag_name: Flag name.
        :return: Description text.
        :raises ValueError: If flag is unknown.
        """
        explanations: dict[str, str] = {
            "repeatable_collections": (
                "Merge repeated assignments for collection-typed arguments instead "
                "of overriding previous values."
            ),
            "interleaved_positionals": (
                "Allow positional arguments to appear between options."
            ),
            "allow_combined_short": (
                "Allow compact short boolean forms like '-abc' as '-a -b -c'."
            ),
            "allow_inline_short_value": (
                "Allow inline values in short options (for example '-p8080')."
            ),
            "allow_long_equals": (
                "Allow '--name=value' assignment syntax for long options."
            ),
            "allow_short_equals": (
                "Allow '-n=value' assignment syntax for short options."
            ),
            "allow_values_starting_with_dash": (
                "Allow option values to begin with '-' even when they look like options."
            ),
            "allow_negative_bool_forms": (
                "Allow '--no-<name>' forms for boolean options to set them to False."
            ),
            "parse_literal_values": (
                "Use literal parsing for containers and mappings when value strings "
                "look like Python literals."
            ),
            "enforce_positional_only": (
                "Reject option-style usage for arguments declared positional_only."
            ),
            "enforce_kwarg_only": (
                "Reject positional usage for arguments declared kwarg_only."
            ),
            "unknown_as_positional": (
                "Treat unknown option-like tokens as positional values when possible."
            ),
            "option_terminator": (
                "Token that ends option parsing and switches all remaining input to positional mode."
            ),
            "duplicate_policy": (
                "Conflict handling for repeated non-collection assignments: "
                "'last', 'first', or 'error'."
            ),
        }
        key = flag_name.strip()
        if key not in explanations:
            raise ValueError(f"Unknown flag '{flag_name}'. Known flags: {', '.join(explanations)}")
        return explanations[key]

    @staticmethod
    def _is_collection_type(tp: _ty.Any) -> bool:
        """Check whether a type represents a sequence/set container."""
        origin = _ty.get_origin(tp)
        return tp in (list, tuple, set) or origin in (list, tuple, set)

    @staticmethod
    def _is_mapping_type(tp: _ty.Any) -> bool:
        """Check whether a type represents a mapping container."""
        origin = _ty.get_origin(tp)
        return tp is dict or origin is dict

    @staticmethod
    def _is_bool_type(tp: _ty.Any) -> bool:
        """Check whether a type resolves to boolean semantics."""
        if tp is bool:
            return True
        origin = _ty.get_origin(tp)
        args = _ty.get_args(tp)
        return origin is _ty.Union and bool in args

    @staticmethod
    def _is_negative_number(token: str) -> bool:
        """Return whether token looks like a negative numeric literal."""
        if len(token) < 2 or token[0] != "-":
            return False
        try:
            float(token)
            return True
        except Exception:
            return False

    @staticmethod
    def _flatten_once(value: _ty.Any) -> list[_ty.Any]:
        """Flatten one nesting level when value is an iterable container."""
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    def _pack_multi_values(self, arg: Argument, values: list[_ty.Any]) -> _ty.Any:
        """Pack multiple consumed values into an argument-appropriate shape."""
        if len(values) == 1:
            return values[0]
        if self._is_mapping_type(arg.type):
            merged: dict[_ty.Any, _ty.Any] = {}
            for v in values:
                if isinstance(v, dict):
                    merged.update(v)
                else:
                    raise ArgumentParsingError(
                        f"Expected mapping chunks for '{arg.name}', got {type(v).__name__}"
                    )
            return merged
        if self._is_collection_type(arg.type):
            origin = _ty.get_origin(arg.type) or arg.type
            flat: list[_ty.Any] = []
            for v in values:
                flat.extend(self._flatten_once(v))
            if origin is set:
                return set(flat)
            if origin is tuple:
                return tuple(flat)
            return flat
        return values

    def _accepts_option(self, endpoint_path: str, option_spelling: str) -> bool:
        """Check whether one option spelling is enabled by runtime flags."""
        if option_spelling in self._enabled_flags:
            return bool(self._enabled_flags[option_spelling])
        per_endpoint = self._enabled_flags.get(endpoint_path)
        if isinstance(per_endpoint, dict):
            return bool(per_endpoint.get(option_spelling, True))
        return True

    def _build_name_index(self, arguments: list[Argument], endpoint_path: str) -> dict[str, Argument]:
        """Build option-name index with duplicate detection and filtering."""
        idx: dict[str, Argument] = {}
        for arg in arguments:
            long_names = [arg.metavar, *arg.alternative_names, arg.name]
            for n in long_names:
                opt = f"--{n}" if not n.startswith("--") else n
                if not self._accepts_option(endpoint_path, opt):
                    continue
                k = n.removeprefix("-")
                if k in idx and idx[k] is not arg:
                    raise ArgumentParsingError(f"Ambiguous option name '{k}'")
                idx[k] = arg
            if arg.letter:
                opt = f"-{arg.letter}"
                if self._accepts_option(endpoint_path, opt):
                    if arg.letter in idx and idx[arg.letter] is not arg:
                        raise ArgumentParsingError(f"Ambiguous short option '{arg.letter}'")
                    idx[arg.letter] = arg
        return idx

    def _coerce_python_value(self, value: _ty.Any, tp: _ty.Any) -> _ty.Any:
        """Coerce a Python value into one target type recursively."""
        origin = _ty.get_origin(tp)
        args = _ty.get_args(tp)

        if tp is _ty.Any:
            return value
        if tp is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                v = value.strip().lower()
                if v in {"1", "true", "t", "yes", "y", "on"}:
                    return True
                if v in {"0", "false", "f", "no", "n", "off"}:
                    return False
            raise ValueError(f"Cannot coerce {value!r} to bool")
        if origin is _ty.Union:
            last: Exception | None = None
            for opt in args:
                if opt is type(None):  # noqa: E721
                    if value is None:
                        return None
                    continue
                try:
                    return self._coerce_python_value(value, opt)
                except Exception as e:  # pragma: no cover - fallback path
                    last = e
            raise ValueError(f"Cannot coerce {value!r} into union {args!r}") from last
        if origin is _ty.Literal:
            allowed = set(args)
            if value in allowed:
                return value
            raise ValueError(f"Value {value!r} not in Literal{tuple(args)!r}")

        if origin in (list, set, tuple):
            elem_t = args[0] if args else _ty.Any
            if not isinstance(value, (list, tuple, set)):
                value = [value]
            seq = [self._coerce_python_value(v, elem_t) for v in value]
            if origin is set:
                return set(seq)
            if origin is tuple:
                return tuple(seq)
            return seq

        if origin is dict:
            key_t, val_t = (args + (_ty.Any, _ty.Any))[:2]
            if not isinstance(value, dict):
                raise ValueError(f"Expected dict-like value, got {type(value).__name__}")
            return {
                self._coerce_python_value(k, key_t): self._coerce_python_value(v, val_t)
                for k, v in value.items()
            }

        if isinstance(tp, type):
            if isinstance(value, tp):
                return value
            return tp(value)
        return value

    def _coerce_value(self, raw: str, arg: Argument) -> _ty.Any:
        """Coerce one raw token using string and literal-aware strategies."""
        try:
            return self._coerce_from_type(raw, arg)
        except Exception as direct_err:
            if not self.parse_literal_values:
                raise ArgumentParsingError(str(direct_err))
            try:
                lit = ast.literal_eval(raw)
            except Exception:
                # Fallback: parse simple "k=v,k2=v2" dict syntax when mapping expected.
                if self._is_mapping_type(arg.type) and "=" in raw:
                    parts = [p for p in raw.split(",") if p.strip()]
                    parsed_map: dict[_ty.Any, _ty.Any] = {}
                    key_t: _ty.Any = str
                    val_t: _ty.Any = str
                    o = _ty.get_origin(arg.type)
                    a = _ty.get_args(arg.type)
                    if o is dict and len(a) >= 2:
                        key_t, val_t = a[0], a[1]
                    for part in parts:
                        key_raw, sep, val_raw = part.partition("=")
                        if not sep:
                            raise ArgumentParsingError(
                                f"Invalid mapping entry '{part}' for '{arg.name}'"
                            )
                        key = self._coerce_python_value(key_raw.strip(), key_t)
                        val = self._coerce_python_value(val_raw.strip(), val_t)
                        parsed_map[key] = val
                    return parsed_map
                raise ArgumentParsingError(
                    f"Could not convert '{raw}' to {arg.type} for '{arg.name}'"
                ) from direct_err
            try:
                return self._coerce_python_value(lit, arg.type)
            except Exception as literal_err:
                raise ArgumentParsingError(
                    f"Could not convert '{raw}' to {arg.type} for '{arg.name}'"
                ) from literal_err

    def _finalize_value(self, arg: Argument, value: _ty.Any) -> _ty.Any:
        """Apply choices and custom validation hooks."""
        self._validate_choices(value, arg)
        if arg.checking_func is None:
            return value
        checked = arg.checking_func(arg, value)
        if isinstance(checked, ArgumentParsingError):
            raise checked
        return checked

    def _merge_value(self, parsed: dict[str, _ty.Any], arg: Argument, value: _ty.Any) -> None:
        """Merge one argument value into parse output according to policies."""
        collection_like = self._is_collection_type(arg.type) or self._is_mapping_type(arg.type)
        if arg.name not in parsed:
            parsed[arg.name] = value
            return

        if not collection_like or not self.repeatable:
            if self.duplicate_policy == "first":
                return
            if self.duplicate_policy == "error":
                raise ArgumentParsingError(f"Argument '{arg.name}' provided more than once")
            parsed[arg.name] = value
            return

        existing = parsed[arg.name]
        if isinstance(existing, dict):
            if not isinstance(value, dict):
                raise ArgumentParsingError(f"Cannot merge non-mapping value into '{arg.name}'")
            existing.update(value)
            return
        if isinstance(existing, set):
            existing.update(self._flatten_once(value))
            return
        if isinstance(existing, tuple):
            parsed[arg.name] = existing + tuple(self._flatten_once(value))
            return
        if isinstance(existing, list):
            existing.extend(self._flatten_once(value))
            return
        parsed[arg.name] = value

    def _nargs_bounds(self, arg: Argument) -> tuple[int, int | None, _ty.Any]:
        """Return normalized ``(min, max, spec)`` tuple for an argument."""
        return arg.nargs.min, arg.nargs.max, arg.nargs.spec

    def _desired_count(self, min_n: int, max_n: int | None, spec: _ty.Any) -> int | None:
        """Compute preferred value count from nargs strategy."""
        if max_n is not None and min_n == max_n:
            return min_n
        if hasattr(spec, "n"):
            return spec.n
        if getattr(spec, "name", None) == "MANY":
            return max_n
        return min_n

    def _looks_like_option(self, token: str, name_index: dict[str, Argument]) -> bool:
        """Return whether a token should be treated as an option marker."""
        if token == self.option_terminator:
            return True
        if token == "-" or not token.startswith("-"):
            return False
        if self.allow_values_starting_with_dash and self._is_negative_number(token):
            return False
        if token.startswith("--"):
            key = token[2:].split("=", 1)[0]
            if key in name_index:
                return True
            if self.allow_negative_bool_forms and key.startswith("no-") and key[3:] in name_index:
                return True
            return not self.unknown_as_positional
        body = token[1:]
        if not body:
            return False
        first = body[0]
        if first in name_index:
            return True
        return not self.unknown_as_positional

    def _consume_values(
        self,
        args: list[str],
        start_idx: int,
        arg: Argument,
        name_index: dict[str, Argument],
        options_mode: bool,
        option_token_idx: int,
    ) -> tuple[_ty.Any, int]:
        """Consume one argument's values based on nargs configuration."""
        min_n, max_n, spec = self._nargs_bounds(arg)
        preferred = self._desired_count(min_n, max_n, spec)
        collected: list[_ty.Any] = []
        i = start_idx

        while i < len(args):
            if max_n is not None and len(collected) >= max_n:
                break
            tok = args[i]
            if options_mode and self._looks_like_option(tok, name_index):
                break
            collected.append(self._coerce_value(tok, arg))
            i += 1
            if preferred is not None and preferred >= 0 and len(collected) >= preferred:
                if getattr(spec, "name", None) != "MANY":
                    break

        if len(collected) < min_n:
            raise ArgumentParsingError(
                f"Expected at least {min_n} value(s) for '{arg.name}', got {len(collected)}",
                idx=option_token_idx,
            )
        return self._pack_multi_values(arg, collected), i

    def parse_args(self, args: list[str], arguments: "list[Argument]", endpoint_path: str,
                   endpoint_help_func: _a.Callable[[], str]) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """Parse tokens with stream semantics and advanced option handling.

        :param args: Raw CLI tokens.
        :param arguments: Declared argument metadata.
        :param endpoint_path: Endpoint identifier for diagnostics.
        :return: Parsed ``(positionals, kwargs)``.
        """
        if self.duplicate_policy not in {"last", "first", "error"}:
            raise ValueError("TokenStreamParser flag 'duplicate_policy' must be one of: 'last', 'first', 'error'")

        name_index = self._build_name_index(arguments, endpoint_path)
        positional_args = [a for a in arguments if not a.kwarg_only]
        positional_idx = 0
        parsed: dict[str, _ty.Any] = {}

        i = 0
        options_mode = True
        while i < len(args):
            tok = args[i]

            if options_mode and tok == self.option_terminator:
                options_mode = False
                i += 1
                continue

            if options_mode and tok.startswith("--") and tok != "--":
                payload = tok[2:]
                key, eq, inline_value = payload.partition("=")
                negated = False
                if self.allow_negative_bool_forms and key.startswith("no-") and key[3:] in name_index:
                    key = key[3:]
                    negated = True
                    eq = ""
                    inline_value = ""

                arg = name_index.get(key)
                if arg is None:
                    if self.unknown_as_positional:
                        # fall through into positional parsing
                        pass
                    else:
                        raise ArgumentParsingError(f"Unknown argument: --{key}", idx=i, endpoint_path=endpoint_path)
                else:
                    if self.enforce_positional_only and arg.positional_only:
                        raise ArgumentParsingError(
                            f"Argument '{arg.name}' is positional-only and cannot be used as an option",
                            idx=i,
                            endpoint_path=endpoint_path,
                        )
                    if eq and not self.allow_long_equals:
                        raise ArgumentParsingError(
                            f"Inline long assignment '--{key}=...' is disabled",
                            idx=i,
                            endpoint_path=endpoint_path,
                        )

                    if self._is_bool_type(arg.type):
                        if negated:
                            value = False
                            next_i = i + 1
                        elif eq:
                            value = self._coerce_value(inline_value, arg)
                            next_i = i + 1
                        else:
                            value = True
                            next_i = i + 1
                    else:
                        if negated:
                            raise ArgumentParsingError(
                                f"'--no-{key}' is only valid for boolean options",
                                idx=i,
                                endpoint_path=endpoint_path,
                            )
                        if eq:
                            value = self._coerce_value(inline_value, arg)
                            next_i = i + 1
                        else:
                            value, next_i = self._consume_values(
                                args, i + 1, arg, name_index, options_mode=True, option_token_idx=i
                            )

                    value = self._finalize_value(arg, value)
                    self._merge_value(parsed, arg, value)
                    i = next_i
                    continue

            if options_mode and tok.startswith("-") and tok not in {"-", "--"}:
                body = tok[1:]
                key, eq, inline_value = body.partition("=")

                if eq and not self.allow_short_equals:
                    raise ArgumentParsingError(
                        f"Inline short assignment '-{key}=...' is disabled",
                        idx=i,
                        endpoint_path=endpoint_path,
                    )

                if len(key) > 1 and not eq and self.allow_combined_short:
                    if all((ch in name_index and self._is_bool_type(name_index[ch].type)) for ch in key):
                        for ch in key:
                            a = name_index[ch]
                            if self.enforce_positional_only and a.positional_only:
                                raise ArgumentParsingError(
                                    f"Argument '{a.name}' is positional-only and cannot be used as an option",
                                    idx=i,
                                    endpoint_path=endpoint_path,
                                )
                            value = self._finalize_value(a, True)
                            self._merge_value(parsed, a, value)
                        i += 1
                        continue

                inline_attached = ""
                if not eq and len(key) > 1 and self.allow_inline_short_value:
                    candidate_key = key[0]
                    if candidate_key in name_index and not self._is_bool_type(name_index[candidate_key].type):
                        inline_attached = key[1:]
                        key = candidate_key

                arg = name_index.get(key)
                if arg is None:
                    if self.unknown_as_positional:
                        # fall through into positional parsing
                        pass
                    else:
                        raise ArgumentParsingError(f"Unknown argument: -{key}", idx=i, endpoint_path=endpoint_path)
                else:
                    if self.enforce_positional_only and arg.positional_only:
                        raise ArgumentParsingError(
                            f"Argument '{arg.name}' is positional-only and cannot be used as an option",
                            idx=i,
                            endpoint_path=endpoint_path,
                        )
                    if self._is_bool_type(arg.type):
                        value = True if not eq else self._coerce_value(inline_value, arg)
                        next_i = i + 1
                    else:
                        if eq:
                            value = self._coerce_value(inline_value, arg)
                            next_i = i + 1
                        elif inline_attached:
                            value = self._coerce_value(inline_attached, arg)
                            next_i = i + 1
                        else:
                            value, next_i = self._consume_values(
                                args, i + 1, arg, name_index, options_mode=True, option_token_idx=i
                            )
                    value = self._finalize_value(arg, value)
                    self._merge_value(parsed, arg, value)
                    i = next_i
                    continue

            if options_mode and not self.interleaved and tok and not tok.startswith("-"):
                options_mode = False

            if positional_idx >= len(positional_args):
                raise ArgumentParsingError(
                    f"Unexpected positional argument: {tok}",
                    idx=i,
                    endpoint_path=endpoint_path,
                )

            parg = positional_args[positional_idx]
            positional_idx += 1
            if self.enforce_kwarg_only and parg.kwarg_only:
                raise ArgumentParsingError(
                    f"Argument '{parg.name}' is keyword-only and cannot be used positionally",
                    idx=i,
                    endpoint_path=endpoint_path,
                )

            value, next_i = self._consume_values(
                args, i, parg, name_index, options_mode=options_mode, option_token_idx=i
            )
            value = self._finalize_value(parg, value)
            self._merge_value(parsed, parg, value)
            i = next_i

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
    def parse_args(self, args: list[str], arguments: "list[Argument]", endpoint_path: str,
                   endpoint_help_func: _a.Callable[[], str]) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
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

    def parse_args(self, args: list[str], arguments: "list[Argument]", endpoint_path: str,
                   endpoint_help_func: _a.Callable[[], str]) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
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

    def parse_args(self, args: list[str], arguments: "list[Argument]", endpoint_path: str,
                   endpoint_help_func: _a.Callable[[], str]) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
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

    def parse_args(self, args: list[str], arguments: "list[Argument]", endpoint_path: str,
                   endpoint_help_func: _a.Callable[[], str]) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
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
