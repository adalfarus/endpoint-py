from abc import ABC
from collections import defaultdict
from dataclasses import dataclass
import enum
import abc

# Internal imports
from .functional import BrokenType, NoDefault, pretty_type

# Standard typing imports for aps
import typing_extensions as _te
import collections.abc as _a
import typing as _ty

if _ty.TYPE_CHECKING:
    import _typeshed as _tsh
import types as _ts

__all__ = ["ArgumentParsingError", "TokenStream", "NativeParserFragment", "NativeIterableParserFragment",
           "NativeParser", "Argument", "Parser", "NArgsMode", "NArgsSpec"]


class Parser(metaclass=abc.ABCMeta):
    """Abstract parser interface for endpoint argument parsing.

    Concrete parsers implement this contract to expose supported flags,
    explain configuration options, and parse CLI tokens into positional and
    keyword values.
    """
    IS_FULLY_FEATURED: bool = False

    @abc.abstractmethod
    def __init__(self, enabled_flags: dict[str, _ty.Any]) -> None:
        """Initialize parser instance.

        :param enabled_flags: Parser-specific flags.
        :return: None.
        """
        ...
    @abc.abstractmethod
    def list_known_flags(self) -> dict[str, type[_ty.Any]]:
        """List supported parser flags.

        :return: Mapping of flag names to expected value types.
        """
        ...
    @abc.abstractmethod
    def explain_flag(self, flag_name: str) -> str:
        """Explain a parser flag.

        :param flag_name: Flag name to explain.
        :return: Human-readable flag description.
        """
        ...
    @abc.abstractmethod
    def parse_args(self, args: list[str], arguments: "list[Argument]", endpoint_path: str
                   ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """Parse CLI arguments.

        :param args: Raw CLI tokens.
        :param arguments: Endpoint argument definitions.
        :param endpoint_path: Endpoint identifier for diagnostics.
        :return: Parsed ``(positional, keyword)`` values.
        """
        ...


class NArgsSpec(enum.Enum):
    """Qualitative argument-count specifier.

    Used together with :class:`NArgsMode.MIN_MAX` to express whether a parser
    should prefer few or many values when an exact count is not fixed.
    """
    FEW = 1
    MANY = 2
    class NUMBER:
        """Numeric nargs preference wrapper."""
        def __init__(self, n: int | None) -> None:
            """Initialize numeric preference.

            :param n: Preferred number of values, or ``None`` when unconstrained.
            :return: None.
            """
            self.n: int | None = n
class NArgsMode(enum.Enum):
    """Nargs mode definitions used by endpoint arguments."""
    ONE = 1
    ZERO_OR_ONE = 2
    class ONE_OR_MORE:
        """Marker for one-or-more values."""
        def __init__(self, spec: NArgsSpec | NArgsSpec.NUMBER):
            """Initialize one-or-more spec.

            :param spec: Strategy used when value count can vary.
            :return: None.
            """
            self.spec: NArgsSpec | NArgsSpec.NUMBER = spec
    class ZERO_OR_MORE:
        """Marker for zero-or-more values."""
        def __init__(self, spec: NArgsSpec | NArgsSpec.NUMBER):
            """Initialize zero-or-more spec.

            :param spec: Strategy used when value count can vary.
            :return: None.
            """
            self.spec: NArgsSpec | NArgsSpec.NUMBER = spec

    class NUMBER:
        """Exact number-of-values wrapper."""
        def __init__(self, n: int) -> None:
            """Initialize exact nargs count.

            :param n: Required number of consumed values.
            :return: None.
            """
            self.n: int = n
    class MIN_MAX:
        """Explicit ``min``/``max`` bounds for value counts."""
        def __init__(self, min_: int, max_: int | None, spec: NArgsSpec | NArgsSpec.NUMBER = NArgsSpec.FEW) -> None:
            """Initialize lower/upper nargs bounds.

            :param min_: Minimum allowed number of consumed values.
            :param max_: Maximum allowed number of consumed values, or ``None``.
            :param spec: Preference hint used by parsers when ambiguous.
            :return: None.
            """
            if min_ < 0 or (max_ and max_ < 0):
                raise ValueError("Min and max both need to be >= 0")
            self.min: int = min_
            self.max: int | None = max_
            self.spec: NArgsSpec | NArgsSpec.NUMBER = spec
        def is_lower_max(self, x: int) -> bool:
            """Return whether ``x`` is still below the configured maximum.

            :param x: Current consumed value count.
            :return: ``True`` if another value may still be consumed.
            """
            if self.max is None:
                return True
            return x < self.max
        def is_higher_min(self, x: int) -> bool:
            """Return whether ``x`` is above the configured minimum.

            :param x: Current consumed value count.
            :return: ``True`` if minimum constraints are satisfied.
            """
            return x > self.min
C = _ty.TypeVar("C")
@dataclass
class Argument:
    """Normalized endpoint argument metadata.

    Instances of this dataclass are shared by parser implementations to
    describe accepted names, expected types, defaults, nargs constraints, and
    rendering hints for help text.
    """
    name: str
    alternative_names: list[str]
    letter: str | None
    type: type[C]
    broken_type: BrokenType
    default: C | NoDefault
    choices: list[C]
    required: bool
    positional_only: bool
    kwarg_only: bool
    help: str
    metavar: str
    nargs: NArgsMode.MIN_MAX
    checking_func: "_a.Callable[[Argument, _ty.Any], _ty.Any | ArgumentParsingError] | None"

    # Rendering helpers
    def _is_boolean(self) -> bool:
        """Return whether the argument behaves like a boolean switch.

        :return: ``True`` for ``bool`` and normalized bool unions.
        """
        return bool is self.broken_type.base_type or (self.broken_type.base_type is _ty.Union
                                                      and len(self.broken_type.arguments) == 1)

    def option_names(self) -> str:
        """Build formatted option aliases.

        :return: Comma-separated option names.
        """
        parts: list[str] = []

        if self.letter:
            parts.append(f"-{self.letter}")

        for n in [self.metavar, *self.alternative_names]:
            if n.startswith("-"):
                parts.append(n)
            else:
                parts.append(f"--{n}")

        # stable de-dupe
        return ", ".join(dict.fromkeys(parts))

    def usage_fragment(self) -> str:
        """Build usage-line fragment for this argument.

        :return: Usage fragment string.
        """
        opt = f"--{self.metavar}" if not self.metavar.startswith("-") else self.metavar
        frags: list[str]

        if self._is_boolean():
            frags = [opt]
        elif self.positional_only:
            frags = [self.name.rstrip()]
        elif self.kwarg_only:
            frags = [f"{opt} {self.name}".rstrip()]
        else:
            frags = [self.name.rstrip(), f"{opt} {self.name}".rstrip()]

        return " ".join(frag if self.required else f"[{frag}]" for frag in frags)

    def left_column(self) -> str:
        """Build left help-column text.

        :return: Left-column string.
        """
        names = ""
        if not self.kwarg_only:
            names += self.name + " / "
        names += self.option_names()
        mv = self.name  # self.computed_metavar()

        if mv and not self._is_boolean():
            names = f"{names} {mv}".rstrip()

        return names

    def meta_parts(self) -> list[str]:
        """Build metadata parts for help output.

        :return: Metadata parts.
        """
        meta: list[str] = []

        if self.required:
            meta.append("required")

        if not isinstance(self.default, NoDefault):
            meta.append(f"default: {self.default!r}")

        meta.append(f"type: {pretty_type(self.type)}")

        if self.choices:
            vals = ", ".join(repr(v) for v in self.choices[:8])
            if len(self.choices) > 8:
                vals += ", …"
            meta.append(f"choices: {vals}")

        return meta

    def right_column(self) -> str:
        """Build right help-column text.

        :return: Right-column string.
        """
        text = (self.help or "").strip()
        meta = self.meta_parts()

        if meta:
            text = (text + (" " if text else "") + f"({'; '.join(meta)})").strip()

        return text

    def __hash__(self) -> int:
        """Hash by canonical metavar for deterministic set/dict usage.

        :return: Hash of ``self.metavar``.
        """
        return hash(self.metavar)

    def as_readable(self) -> str:
        """Return short debug representation.

        :return: Human-readable argument identifier.
        """
        return f"Argument({self.metavar})"


class _BaseSeverity(enum.IntEnum):
    """Shared base enum for parser severities."""
    def to_str(self) -> str:
        """Return lowercase enum member name.

        :return: Lowercase severity name.
        """
        return self.name.lower()


class ParsingErrorSeverity(_BaseSeverity):
    """Severity levels for token-level parsing errors."""
    DOES_NOT_APPLY = 0
    CAN_CONTINUE = 1
    SKIP_TO_NEXT_SPACE = 2
    REACHED_INVALID_STATE = 4


class ValueParsingSeverity(_BaseSeverity):
    """Severity levels for value-conversion/parsing errors."""
    DOES_NOT_APPLY = 0
    NOT_REQUIRED_POS = 1
    REQUIRED_POS = 2
    NOT_REQUIRED = 4
    REQUIRED = 8
    NOT_REQUIRED_ARG = 16
    REQUIRED_ARG = 32


class ArgumentParsingError(Exception):
    """Exception raised when an error occurs during argument parsing.

    This exception is used to indicate issues while tokenizing/parsing CLI
    input. It carries an optional stream snapshot so callers can present
    precise diagnostics to users.

    :param message: Human-readable error message.
    :param severity: Parsing severity used for recovery decisions.
    :param stream: Optional stream position context.
    :return: None.
    """

    def __init__(self, message: str, severity: ParsingErrorSeverity = ParsingErrorSeverity.DOES_NOT_APPLY,
                 stream: "TokenStream | None" = None) -> None:
        """Initialize parsing error object.

        :param message: Human-readable error message.
        :param severity: Recovery/continuation severity hint.
        :param stream: Optional token stream snapshot.
        :return: None.
        """
        super().__init__(message)
        self.message: str = message
        self.severity: ParsingErrorSeverity = severity
        self.stream: "TokenStream | None" = stream

    def raise_(self) -> _ty.Self:
        """Raise immediately for fatal severities.

        :return: ``self`` when non-fatal.
        :raises ArgumentParsingError: If severity is invalid-state.
        """
        if self.severity == ParsingErrorSeverity.REACHED_INVALID_STATE:
            raise self
        return self
    def show(self) -> str:
        """Render inline stream pointer if available.

        :return: Stream visualization or empty string.
        """
        if self.stream is not None:
            return self.stream.show()
        return ""
    def __str__(self) -> str:
        """Return diagnostic string representation."""
        return f"ArgumentParsingError(message='{self.message}', stream={self.stream})"
    def __repr__(self) -> str:
        """Return debug representation."""
        return str(self)


class ValueParsingError(Exception):
    """Error raised while converting token text into typed argument values."""
    def __init__(self, message: str, argument: Argument | None, parsing_errors: list[ArgumentParsingError] | None = None,
                 severity: ValueParsingSeverity = ValueParsingSeverity.DOES_NOT_APPLY) -> None:
        """Initialize value parsing error.

        :param message: Human-readable error message.
        :param argument: Associated argument, if known.
        :param parsing_errors: Underlying token-level parser errors.
        :param severity: Severity classification for routing/filtering.
        :return: None.
        """
        super().__init__(message)
        self.message: str = message
        self.argument: Argument | None = argument
        self.parsing_errors: list[ArgumentParsingError] = parsing_errors or list()
        self.severity: ValueParsingSeverity = severity

    def __str__(self) -> str:
        """Return concise value-parsing error text."""
        return f"ValueParsingError(message='{self.message}', severity={self.severity})"
    def __repr__(self) -> str:
        """Return debug representation."""
        return str(self)


class TokenStream:
    """Mutable cursor over a source string used by parser fragments."""
    def __init__(self, base_string: str) -> None:
        """Initialize stream.

        :param base_string: Source text to read.
        :return: None.
        """
        self._base_string: str = base_string
        self._index: int = 0

    def consume(self, i: int = 1) -> str | None:
        """Consume one or more characters.

        :param i: Number of characters to include in returned token.
        :return: Consumed token, or ``None`` at EOF.
        """
        base: str = ""
        if i > 1:
            for i in range(i-1):
                b = self.reverse()
                if b is None:
                    break
                base += b
        if self._index == len(self._base_string):
            return None
        token: str = base + self._base_string[self._index]
        self._index += 1
        return token

    def consume_remaining(self) -> str:
        """Return unconsumed remainder without moving cursor."""
        return self._base_string[self._index:]

    def reverse(self, i: int = 1) -> bool:
        """Move cursor backward.

        :param i: Number of characters to rewind.
        :return: ``True`` if rewind succeeded for at least one char.
        """
        if i > 1:
            for i in range(i-1):
                self.reverse()
        if self._index == 0:
            return False
        self._index -= 1
        return True

    def restart(self) -> None:
        """Reset stream cursor to start."""
        self._index = 0

    def copy(self) -> _ty.Self:
        """Create shallow copy preserving current index.

        :return: Copied token stream.
        """
        new_stream: TokenStream = TokenStream(self._base_string)
        new_stream._index = self._index
        return new_stream

    def show(self) -> str:
        """Render source with current cursor marker.

        :return: Marked string representation.
        """
        if len(self._base_string) == 0:
            return ""
        return (self._base_string[:self._index-1]
                       + ">" + self._base_string[max(0, self._index-1)] + "<"
                       + self._base_string[self._index:])

    def get_index(self) -> int:
        """Return current cursor index."""
        return self._index

    def set_index(self, index: int) -> None:
        """Set cursor index.

        :param index: New absolute cursor position.
        :return: None.
        """
        if 0 > index > len(self._base_string):
            raise ValueError(f"New index {index} is not between 0 and len(self._base_string).")
        self._index = index

    def get_base_string(self) -> str:
        """Return original source string."""
        return self._base_string

    def __str__(self) -> str:
        """Return stream state with cursor marker."""
        string: str = self.show()
        return f"TokenStream(_index={self._index}, _base_string='{string}')"
    def __repr__(self) -> str:
        """Return debug representation."""
        return str(self)


X = _ty.TypeVar("X")
class NativeParserFragment(_ty.Generic[X]):
    """Base fragment for parsing one logical value type.

    A fragment receives raw token lists for a single argument and returns
    either a parsed value or :class:`ArgumentParsingError`.
    """
    REPLACE: bool = False
    REPLACE_WITH_SET: bool = False
    def _parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        """Implement type-specific parsing for one argument value.

        :param input_lst: Candidate tokens associated with one argument.
        :param last_failed: Whether prior alternative parsing failed.
        :return: Parsed value or parsing error.
        """
        raise NotImplementedError()
    def _iter(self, input_: X, composite_type: BrokenType) -> _a.Iterable[tuple[_ty.Any, str | list[str], tuple[BrokenType, ...]]]:
        """Iterate nested members for composite-type recursion."""
        raise NotImplementedError()
    def _set_one(self, input_: X, to_set: tuple[_ty.Any, _ty.Any]) -> None | X:
        """Apply one replacement produced by recursive parsing."""
        raise NotImplementedError()

    def parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        """Parse value candidate using fragment implementation."""
        return self._parse(input_lst, last_failed)
    def iter(self, input_: X, composite_type: BrokenType) -> _a.Iterable[tuple[_ty.Any, str | list[str], tuple[BrokenType, ...]]]:
        """Iterate composite members or raise for scalar fragments."""
        try:
            return self._iter(input_, composite_type)
        except NotImplementedError:
            raise ValueError("This is a basic data type, not a composite data type, it can't be iterated.")
    def set(self, input_: X, to_set: list[tuple[_ty.Any, _ty.Any]]) -> None | X:
        """Apply one or more recursive replacements to composite value."""
        try:
            for to in to_set:
                if self.REPLACE_WITH_SET:
                    input_ = self._set_one(input_, to)
                else:
                    self._set_one(input_, to)
        except NotImplementedError:
            raise ValueError("This is a basic data type, not a composite data type, it can't be set.")
        return input_  # Can always be returned as no action is taken except the flag is set

class NativeUnionParserFragment(NativeParserFragment):
    """Pass-through fragment used while trying union alternatives."""
    REPLACE = True

    def _parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        return input_lst

    def _iter(self, input_: X, composite_type: BrokenType) -> _a.Iterable[tuple[_ty.Any, str | list[str], tuple[BrokenType, ...]]]:
        return [(None, input_, composite_type.arguments)]

class NativeStringParserFragment(NativeParserFragment):
    """Parse string arguments with optional quote unwrapping."""
    def __init__(self, parse_python_types: bool = True, delimiters: str = "'\"") -> None:
        self._parse_python_types: bool = parse_python_types
        self._delimiters: str = delimiters

    def _parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        if len(input_lst) == 1 or last_failed:
            input_: str = " ".join(input_lst)
            if self._parse_python_types:
                for delimiter in self._delimiters:
                    if input_.startswith(delimiter) and input_.endswith(delimiter):
                        return input_.removeprefix(delimiter).removesuffix(delimiter)
            return input_
        fake_stream: TokenStream = TokenStream("'" + "' '".join(input_lst) + "'")
        fake_stream.set_index(len(input_lst[0]) + 4)
        return ArgumentParsingError("A string can't be composed of multiple inputs.", ParsingErrorSeverity.DOES_NOT_APPLY, fake_stream)

class NativeIntegerParserFragment(NativeParserFragment):
    """Parse integer values from one token."""
    def _parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        if len(input_lst) == 1:
            out: int
            try:
                out = int(input_lst[0].strip())
            except Exception as e:
                return ArgumentParsingError(f"Failed to convert to an integer with error: '{e}'", ParsingErrorSeverity.DOES_NOT_APPLY, TokenStream(input_lst[0]))
            return out
        fake_stream: TokenStream = TokenStream(" ".join(input_lst))
        fake_stream.set_index(len(input_lst[0]) + 1 + min(len(input_lst[1]), 1))  # To prevent error if len(input_lst)=2 and input_lst[1]=""
        return ArgumentParsingError("An integer can't be composed of multiple inputs.", ParsingErrorSeverity.DOES_NOT_APPLY, fake_stream)

class NativeFloatingPointNumberParserFragment(NativeParserFragment):
    """Parse floating-point values from one token."""
    def _parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        if len(input_lst) == 1:
            out: float
            try:
                out = float(input_lst[0].strip())
            except Exception as e:
                return ArgumentParsingError(f"Failed to convert to a floating point number with error: '{e}'", ParsingErrorSeverity.DOES_NOT_APPLY, TokenStream(input_lst[0]))
            return out
        fake_stream: TokenStream = TokenStream(" ".join(input_lst))
        fake_stream.set_index(len(input_lst[0]) + 1 + min(len(input_lst[1]), 1))  # To prevent error if len(input_lst)=2 and input_lst[1]=""
        return ArgumentParsingError("A floating point number can't be composed of multiple inputs.", ParsingErrorSeverity.DOES_NOT_APPLY, fake_stream)

class NativeIterableParserFragment(NativeParserFragment):
    """Parse comma-separated iterable-like values.

    Handles escaped characters, quoted strings, and nested bracket blocks.
    """
    def __init__(self, parse_python_types: bool = True, error_if_unsure: bool = True,
                 convert_to_type: type[_ty.Any] = list, assignment_tokens: str = ":=",
                 brackets: dict[str, str] | None = None) -> None:
        self._parse_python_types: bool = parse_python_types
        self._error_if_unsure: bool = error_if_unsure
        self._convert_to_type: type[_ty.Any] = convert_to_type
        self._assignment_tokens: str = assignment_tokens
        self._brackets: dict[str, str] = brackets or {"(": ")"}

    def _parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        input_valid: bool = False
        if len(input_lst) > 1:
            return self._convert_to_type(input_lst)  # Used multiple to make list like --lst elem1 --lst elem2 --lst elem3,elem4
        elif self._parse_python_types:
            for start, end in self._brackets.items():
                if input_lst[0].startswith(start) and input_lst[0].endswith(end):
                    input_lst[0] = input_lst[0].removeprefix(start).removesuffix(end)
                    input_valid = True
        stream: TokenStream = TokenStream(input_lst[0])
        return_lst: list = list()
        curr_elem: str = ""
        skip_next: bool = False

        while token := stream.consume():
            if skip_next:
                skip_next = False
                curr_elem += token
            elif token == "\\":
                skip_next = True
            elif token == " ":
                pass
            elif token == ",":
                return_lst.append(curr_elem)
                curr_elem = ""
                input_valid = True
            elif token in ("'", '"') and curr_elem == "":
                stream.reverse()
                curr_elem = NativeParser._parse_string(stream, token)
                next_token = stream.consume()
                if next_token is not None and next_token not in " ," + self._assignment_tokens:
                    return ArgumentParsingError("You cannot have a non delimiting token next to the end of a string.", ParsingErrorSeverity.SKIP_TO_NEXT_SPACE, stream.copy())
                elif next_token is None:
                    break
                stream.reverse()
            elif token in ("(", "[", "{", "<") and curr_elem == "":
                stream.reverse()
                curr_elem = NativeParser._parse_bracket(stream, token)
                next_token = stream.consume()
                if next_token is not None and next_token not in " ," + self._assignment_tokens:
                    return ArgumentParsingError(
                        "You cannot have a non delimiting token next to the end of a string.",
                        ParsingErrorSeverity.SKIP_TO_NEXT_SPACE, stream.copy())
                elif next_token is None:
                    break
                stream.reverse()
            else:
                curr_elem += token
        if curr_elem != "":
            return_lst.append(curr_elem)
        if not input_valid and self._error_if_unsure and not last_failed:
            return ArgumentParsingError("Did not see a single separating token, assuming this is another type.", ParsingErrorSeverity.DOES_NOT_APPLY, stream.copy())
        return self._convert_to_type(return_lst)

    def _iter(self, input_: X, composite_type: BrokenType) -> _a.Iterable[tuple[_ty.Any, str | list[str], tuple[BrokenType, ...]]]:
        input_ = _ty.cast(_a.Iterable[str], input_)
        for i, x in enumerate(input_):
            yield i, x, composite_type.arguments

    def _set_one(self, input_: X, to_set: tuple[_ty.Any, _ty.Any]) -> None | X:
        input_ = _ty.cast(_a.Iterable[str | _ty.Any], input_)
        input_[to_set[0]] = to_set[1]  # (i, parsed_x) are returned

class NativeListParserFragment(NativeIterableParserFragment):
    """List-specialized iterable fragment."""
    def __init__(self, parse_python_types: bool = True, error_if_unsure: bool = True, assignment_tokens: str = ":=",
                 brackets: dict[str, str] | None = None) -> None:
        super().__init__(parse_python_types, error_if_unsure, list, assignment_tokens, brackets or {"[": "]"})

    def _parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        return super()._parse(input_lst, last_failed)  # If parse python types use list brackets

class NativeDictParserFragment(NativeParserFragment):
    """Parse dictionary-like ``key:value`` structures."""
    def __init__(self, parse_python_types: bool = True, list_separators: str = ",:;|", kv_separators: str = ",:=;",
                 ignore_random_separators: bool = False, allow_same_k_and_v_separator: bool = False,
                 assignment_tokens: str = ":=", brackets: dict[str, str] | None = None) -> None:
        self._parse_python_types: bool = parse_python_types
        self._list_separators: str = list_separators
        self._kv_separators: str = kv_separators
        self._ignore_random_separators: bool = ignore_random_separators
        self._allow_same_k_and_v_separator: bool = allow_same_k_and_v_separator
        self._assignment_tokens: str = assignment_tokens
        self._brackets: dict[str, str] = brackets or {"{": "}"}

    def _parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        return_dict: dict[str, str] = dict()
        if len(input_lst) == 1:
            if self._parse_python_types:
                for start, end in self._brackets.items():
                    if input_lst[0].startswith(start) and input_lst[0].endswith(end):
                        input_lst[0] = input_lst[0].removeprefix(start).removesuffix(end)

            stream: TokenStream = TokenStream(input_lst[0])
            curr_key: str = ""
            filling_key: bool = True
            curr_elem: str = ""
            skip_next: bool = False
            chosen_kv_separator: str = ""
            chosen_lst_separator: str = ""
            valid_state: bool = True

            while token := stream.consume():
                if skip_next:
                    skip_next = False
                    curr_elem += token
                elif token == "\\":
                    skip_next = True
                elif token == " ":
                    pass
                elif token in ("'", '"') and curr_elem == "":
                    stream.reverse()
                    curr_elem = NativeParser._parse_string(stream, token)
                    next_token = stream.consume()
                    if next_token is not None and next_token not in " ," + self._assignment_tokens:
                        return ArgumentParsingError(
                            "You cannot have a non delimiting token next to the end of a string.",
                            ParsingErrorSeverity.SKIP_TO_NEXT_SPACE, stream.copy())
                    elif next_token is None:
                        break
                    stream.reverse()
                elif token in ("(", "[", "{", "<") and curr_elem == "":
                        stream.reverse()
                        curr_elem = NativeParser._parse_bracket(stream, token)
                        next_token = stream.consume()
                        if next_token is not None and next_token not in " ," + self._assignment_tokens:
                            return ArgumentParsingError(
                                "You cannot have a non delimiting token next to the end of a string.",
                                ParsingErrorSeverity.SKIP_TO_NEXT_SPACE, stream.copy())
                        elif next_token is None:
                            break
                        stream.reverse()
                elif token in self._kv_separators and chosen_kv_separator == "":
                    chosen_kv_separator = token
                    curr_key = curr_elem
                    curr_elem = ""
                    valid_state = True
                elif token in self._list_separators and chosen_kv_separator != "" and chosen_lst_separator == "":
                    chosen_lst_separator = token
                    if chosen_kv_separator == chosen_lst_separator and not self._allow_same_k_and_v_separator:
                        return ArgumentParsingError(f"Key or value missing, found two of the same key or value separator ({token}), unable to continue.", ParsingErrorSeverity.DOES_NOT_APPLY, stream.copy())
                    return_dict[curr_key] = curr_elem
                    curr_key = curr_elem = ""
                    valid_state = False
                elif token == chosen_kv_separator:
                    if not filling_key:
                        if self._ignore_random_separators:
                            stream.reverse()
                            skip_next = True
                            continue
                        return ArgumentParsingError(f"Key-Value seperator '{token}' in value.",
                                                    ParsingErrorSeverity.DOES_NOT_APPLY, stream.copy())
                    filling_key = False
                    curr_key = curr_elem
                    curr_elem = ""
                    valid_state = True
                elif token == chosen_lst_separator:
                    if filling_key:
                        if self._ignore_random_separators:
                            stream.reverse()
                            skip_next = True
                            continue
                        return ArgumentParsingError(f"Listing seperator '{token}' in key.",
                                                    ParsingErrorSeverity.DOES_NOT_APPLY, stream.copy())
                    return_dict[curr_key] = curr_elem
                    curr_key = curr_elem = ""
                    filling_key = True
                    valid_state = False
                else:
                    curr_elem += token
                    valid_state = True

            if not valid_state:
                return ArgumentParsingError("Did not end in a valid state, did you end on a delimiter?", ParsingErrorSeverity.DOES_NOT_APPLY, stream.copy())

            if curr_key != "":
                return_dict[curr_key] = curr_elem
            elif stream.get_base_string() != "":
                if chosen_kv_separator == "":  # chosen_lst_sep is also "" in this case
                    return_dict[curr_elem] = ""
                elif chosen_kv_separator != "" and chosen_lst_separator == "":
                    return_dict[""] = curr_elem
                elif filling_key:  # We can only check separately as filling_key is irrelevant when choosing separators
                    return_dict[curr_elem] = ""
                else:
                    return_dict[""] = curr_elem
        else:  # Used multiple to make list like --lst elem1,val1 --lst elem2,val2 --lst elem3:elem4
            for elem in input_lst:
                elem_stream = TokenStream(elem)
                skip_next: bool = False
                curr_elem: str = ""

                while token := elem_stream.consume():
                    if skip_next:
                        skip_next = False
                        curr_elem += token
                    elif token == "\\":
                        skip_next = True
                    elif token == " ":
                        pass
                    elif token in ("'", '"') and curr_elem == "":
                        elem_stream.reverse()
                        curr_elem = NativeParser._parse_string(elem_stream, token)
                        next_token = elem_stream.consume()
                        if next_token is not None and next_token not in " ," + self._assignment_tokens:
                            return ArgumentParsingError(
                                "You cannot have a non delimiting token next to the end of a string.",
                                ParsingErrorSeverity.SKIP_TO_NEXT_SPACE, elem_stream.copy())
                        elif next_token is None:
                            break
                        elem_stream.reverse()
                    elif token in ("(", "[", "{", "<") and curr_elem == "":
                        elem_stream.reverse()
                        curr_elem = NativeParser._parse_bracket(elem_stream, token)
                        next_token = elem_stream.consume()
                        if next_token is not None and next_token not in " ," + self._assignment_tokens:
                            return ArgumentParsingError(
                                "You cannot have a non delimiting token next to the end of a string.",
                                ParsingErrorSeverity.SKIP_TO_NEXT_SPACE, elem_stream.copy())
                        elif next_token is None:
                            break
                        elem_stream.reverse()
                    elif token in self._kv_separators:
                        return_dict[curr_elem] = elem_stream.consume_remaining()
                        break
                    else:
                        curr_elem += token
        return return_dict

    def _iter(self, input_: X, composite_type: BrokenType) -> _a.Iterable[tuple[_ty.Any, str | list[str], tuple[BrokenType, ...]]]:
        input_ = _ty.cast(dict[str, str], input_)
        for i, (key, value) in enumerate(input_.items()):
            # As when we remove keys and readd them one by one the next one will always be idx 0. We change val first
            # as the index of k:v will change when doing the key
            yield (0, "val"), value, (composite_type.arguments[1],)  # index 0 has val type in dict[..., ...]
            yield (0, "key"), key, (composite_type.arguments[0],)  # index 0 has key type in dict[..., ...]

    def _set_one(self, input_: X, to_set: tuple[_ty.Any, _ty.Any]) -> None | X:
        input_ = _ty.cast(dict[str | _ty.Any, str | _ty.Any], input_)
        i: int
        type_: _ty.Literal["key", "val"]
        i, type_ = to_set[0]
        parsed_s = to_set[1]
        curr_key: str = list(input_.keys())[i]
        if type_ == "key":
            old_val = input_[curr_key]
            del input_[curr_key]
            input_[parsed_s] = old_val
        elif type_ == "val":
            input_[curr_key] = parsed_s
        else:
            raise ValueError(f"Type '{type_}' is not a valid dict setting type.")

class NativeSetParserFragment(NativeIterableParserFragment):
    """Set-specialized iterable fragment."""
    def __init__(self, parse_python_types: bool = True, error_if_unsure: bool = True, assignment_tokens: str = ":=",
                 brackets: dict[str, str] | None = None) -> None:
        super().__init__(parse_python_types, error_if_unsure, set, assignment_tokens, brackets or {"{": "}"})

    def _parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        return super()._parse(input_lst, last_failed)  # If parse python types use list brackets

    def _iter(self, input_: X, composite_type: BrokenType) -> _a.Iterable[tuple[_ty.Any, str | list[str], tuple[BrokenType, ...]]]:
        input_ = _ty.cast(set[str], input_)
        for x in input_:
            yield x, x, composite_type.arguments

    def _set_one(self, input_: X, to_set: tuple[_ty.Any, _ty.Any]) -> None | X:
        input_ = _ty.cast(set[str | _ty.Any], input_)
        input_.remove(to_set[0])  # Old element
        input_.add(to_set[1])  # Parsed element

class NativeTupleParserFragment(NativeIterableParserFragment):
    """Tuple-specialized iterable fragment."""
    REPLACE_WITH_SET = True
    def __init__(self, parse_python_types: bool = True, error_if_unsure: bool = True, assignment_tokens: str = ":=",
                 brackets: dict[str, str] | None = None) -> None:
        super().__init__(parse_python_types, error_if_unsure, tuple, assignment_tokens, brackets or {"(": ")"})

    def _parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        return super()._parse(input_lst, last_failed)  # If parse python types use list brackets

    def _set_one(self, input_: X, to_set: tuple[_ty.Any, _ty.Any]) -> None | X:
        input_ = _ty.cast(tuple[str | _ty.Any], input_)
        i, val = to_set
        return input_[:i] + (val,) + input_[i+1:]

class NativeComplexParserFragment(NativeParserFragment):
    """Parse complex numbers from one token."""
    def _parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        if len(input_lst) == 1:
            out: complex
            try:
                out = complex(input_lst[0].strip())
            except Exception as e:
                return ArgumentParsingError(f"Failed to convert to a complex number with error: '{e}'", ParsingErrorSeverity.DOES_NOT_APPLY, TokenStream(input_lst[0]))
            return out
        fake_stream: TokenStream = TokenStream(" ".join(input_lst))
        fake_stream.set_index(len(input_lst[0]) + 1 + min(len(input_lst[1]), 1))  # To prevent error if len(input_lst)=2 and input_lst[1]=""
        return ArgumentParsingError("A complex number can't be composed of multiple inputs.", ParsingErrorSeverity.DOES_NOT_APPLY, fake_stream)

class NativeBytesParserFragment(NativeParserFragment):
    """Parse bytes using configured text encoding."""
    def __init__(self, encoding: str = "utf-8") -> None:
        self._encoding: str = encoding

    def _parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        if len(input_lst) == 1 or last_failed:
            out: bytes
            input_: str = " ".join(input_lst)
            try:
                out = bytes(input_.strip(), self._encoding)
            except Exception as e:
                return ArgumentParsingError(f"Failed to convert to a bytes object with error: '{e}'", ParsingErrorSeverity.DOES_NOT_APPLY, TokenStream(input_))
            return out
        fake_stream: TokenStream = TokenStream(" ".join(input_lst))
        fake_stream.set_index(len(input_lst[0]) + 1 + min(len(input_lst[1]), 1))  # To prevent error if len(input_lst)=2 and input_lst[1]=""
        return ArgumentParsingError("A bytes object can't be composed of multiple inputs.", ParsingErrorSeverity.DOES_NOT_APPLY, fake_stream)

class NativeBoolParserFragment(NativeParserFragment):
    """Parse boolean flags as presence/toggle values."""
    def __init__(self, toggle_value: bool = False) -> None:
        self._toggle_value: bool = toggle_value

    def _parse(self, input_lst: list, last_failed: bool) -> X | ArgumentParsingError:
        if not self._toggle_value:
            return True
        return len(input_lst) & 1 == 1  # If a bool flag was set it's true, if it was set twice it's untrue, etc.


E = _ty.TypeVar("E")
class NativeParserEnabledFlags(_ty.TypedDict, total=False):
    """Supported configuration flags for :class:`NativeParser`."""
    PARSER_FRAGMENTS: dict[type[E], type[NativeParserFragment[E]]]

    # Argument flags
    NO_POSITIONAL_ARGS: bool
    SMART_TYPING: bool
    ALLOW_NON_DETERMINISTIC_BEHAVIOUR: bool
    ARGNAME_VALID: str
    ARG_ASSIGNMENT_TOKENS: str
    # ERROR_IF_TOO_MANY_ARGS: bool
    ERROR_IF_TOO_MANY_KWARGS: bool
    IGNORE_VALUE_PARSING_ERROR_BELOW: ValueParsingSeverity
    RETURN_ALL_POSONLY_AS_KWARG: bool

    PARSE_PYTHON_TYPES: bool
    # String flags
    STR_PARSE_PYTHON_TYPES: bool
    STR_DELIMITERS: str
    # Iterable flags
    ITERABLE_PARSE_PYTHON_TYPES: bool
    ITERABLE_ERROR_IF_UNSURE: bool
    ITERABLE_CONVERT_TO_TYPE: type[_ty.Any]
    ITERABLE_ASSIGNMENT_TOKENS: str
    ITERABLE_BRACKETS: dict[str, str]
    # List flags
    LIST_PARSE_PYTHON_TYPES: bool
    LIST_ERROR_IF_UNSURE: bool
    LIST_ASSIGNMENT_TOKENS: str
    LIST_BRACKETS: dict[str, str]
    # Dict flags
    DICT_PARSE_PYTHON_TYPES: bool
    DICT_LIST_SEPARATORS: str
    DICT_KV_SEPARATORS: str
    DICT_IGNORE_RANDOM_SEPARATORS: bool
    DICT_ALLOW_SAME_K_AND_V_SEPARATORS: bool
    DICT_ASSIGNMENT_TOKENS: str
    DICT_BRACKETS: dict[str, str]
    # Set flags
    SET_PARSE_PYTHON_TYPES: bool
    SET_ERROR_IF_UNSURE: bool
    SET_ASSIGNMENT_TOKENS: str
    SET_BRACKETS: dict[str, str]
    # Tuple flags
    TUPLE_PARSE_PYTHON_TYPES: bool
    TUPLE_ERROR_IF_UNSURE: bool
    TUPLE_ASSIGNMENT_TOKENS: str
    TUPLE_BRACKETS: dict[str, str]
    # Bytes flags
    BYTES_ENCODING: str
    # Bool flags
    BOOL_TOGGLE_VALUE: bool


class NativeParser(Parser):
    """Full-featured deterministic endpoint parser.

    This parser tokenizes CLI text, resolves argument names/aliases, applies
    type fragments, and enforces required/default/nargs behavior.
    """
    IS_FULLY_FEATURED = True  # Pos, kwarg, choices, posonly, kwargonly, posorkwarg, complex types, ...

    def __init__(self, enabled_flags: NativeParserEnabledFlags) -> None:
        """Initialize parser and fragment instances from enabled flags.

        :param enabled_flags: Parser and fragment configuration values.
        :return: None.
        """
        self._parser_fragments: dict[type[E], type[NativeParserFragment[E]]] = {
            _ty.Union: NativeUnionParserFragment,
            str: NativeStringParserFragment,
            int: NativeIntegerParserFragment,
            float: NativeFloatingPointNumberParserFragment,
            _a.Iterable: NativeIterableParserFragment,
            list: NativeListParserFragment,
            dict: NativeDictParserFragment,
            set: NativeSetParserFragment,
            tuple: NativeTupleParserFragment,
            complex: NativeComplexParserFragment,
            bytes: NativeBytesParserFragment,
            bool: NativeBoolParserFragment,
            **enabled_flags.get("PARSER_FRAGMENTS", dict())
        }
        # Argument parser flags
        # TODO: Implement NO_POSITIONAL_ARGS (Would mean bool can be paired with other types again)
        self._no_positional_args: bool = enabled_flags.get("NO_POSITIONAL_ARGS", False)
        if self._no_positional_args:
            raise NotImplementedError("The flag NO_POSITIONAL_ARGS is not yet implemented.")
        # TODO: Implement SMART_TYPING (Specifics in parse comment)
        # "Smart" typing will not be implemented (automatically assigning a posarg to another output arg
        # because all ParserFragments failed to parse it. Maybe flag?
        self._smart_typing: bool = enabled_flags.get("SMART_TYPING", False)
        if self._smart_typing:
            raise NotImplementedError("The flag SMART_TYPING is not yet implemented.")
        self._allow_non_deterministic_behaviour: bool = enabled_flags.get("ALLOW_NON_DETERMINISTIC_BEHAVIOUR", True)
        self._argname_valid: str = enabled_flags.get("ARGNAME_VALID", "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        self._arg_assignment_tokens: str = enabled_flags.get("ARG_ASSIGNMENT_TOKENS", ":=")
        # self._error_if_too_many_args: bool = enabled_flags.get("ERROR_IF_TOO_MANY_ARGS", True)
        self._error_if_too_many_kwargs: bool = enabled_flags.get("ERROR_IF_TOO_MANY_KWARGS", True)
        self._ignore_value_parsing_error_below: ValueParsingSeverity = enabled_flags.get("IGNORE_VALUE_PARSING_ERROR_BELOW", ValueParsingSeverity.DOES_NOT_APPLY)
        self._return_all_posonly_as_kwarg: bool = enabled_flags.get("RETURN_ALL_POSONLY_AS_KWARG", True)
        # Type parser flags
        self._parse_python_types: bool = enabled_flags.get("PARSE_PYTHON_TYPES", True)
        # String flags
        self._str_parse_python_types = enabled_flags.get("STR_PARSE_PYTHON_TYPES", self._parse_python_types)
        self._str_delimiters: str = enabled_flags.get("STR_DELIMITERS", "'\"")
        # Integer flags
        # Floating point number flags
        # Iterable flags
        self._iterable_parse_python_types: bool = enabled_flags.get("ITERABLE_PARSE_PYTHON_TYPES", self._parse_python_types)
        self._iterable_error_if_unsure: bool = enabled_flags.get("ITERABLE_ERROR_IF_UNSURE", True)
        self._iterable_convert_to_type: type[_ty.Any] = enabled_flags.get("ITERABLE_CONVERT_TO_TYPE", list)
        self._iterable_assignment_tokens: str = enabled_flags.get("ITERABLE_ASSIGNMENT_TOKENS", ":=")
        self._iterable_brackets: dict[str, str] = enabled_flags.get("ITERABLE_BRACKETS", {"(": ")"})
        # List flags
        self._list_parse_python_types: bool = enabled_flags.get("LIST_PARSE_PYTHON_TYPES", self._parse_python_types)
        self._list_error_if_unsure: bool = enabled_flags.get("LIST_ERROR_IF_UNSURE", True)
        self._list_assignment_tokens: str = enabled_flags.get("LIST_ASSIGNMENT_TOKENS", ":=")
        self._list_brackets: dict[str, str] = enabled_flags.get("LIST_BRACKETS", {"[": "]"})
        # Dict flags
        self._dict_parse_python_types: bool = enabled_flags.get("DICT_PARSE_PYTHON_TYPES", self._parse_python_types)
        self._dict_list_separators: str = enabled_flags.get("DICT_LIST_SEPARATORS", ",:;|")
        self._dict_kv_separators: str = enabled_flags.get("DICT_KV_SEPARATORS", ",:=;")
        self._dict_ignore_random_separators: bool = enabled_flags.get("DICT_IGNORE_RANDOM_SEPARATORS", False)
        self._dict_allow_same_k_and_v_separator: bool = enabled_flags.get("DICT_ALLOW_SAME_K_AND_V_SEPARATORS", False)
        self._dict_assignment_tokens: str = enabled_flags.get("DICT_ASSIGNMENT_TOKENS", ":=")
        self._dict_brackets: dict[str, str] = enabled_flags.get("DICT_BRACKETS", {"{": "}"})
        # Set flags
        self._set_parse_python_types: bool = enabled_flags.get("SET_PARSE_PYTHON_TYPES", self._parse_python_types)
        self._set_error_if_unsure: bool = enabled_flags.get("SET_ERROR_IF_UNSURE", True)
        self._set_assignment_tokens: str = enabled_flags.get("SET_ASSIGNMENT_TOKENS", ":=")
        self._set_brackets: dict[str, str] = enabled_flags.get("SET_BRACKETS", {"{": "}"})
        # Tuple flags
        self._tuple_parse_python_types: bool = enabled_flags.get("TUPLE_PARSE_PYTHON_TYPES", self._parse_python_types)
        self._tuple_error_if_unsure: bool = enabled_flags.get("TUPLE_ERROR_IF_UNSURE", True)
        self._tuple_assignment_tokens: str = enabled_flags.get("TUPLE_ASSIGNMENT_TOKENS", ":=")
        self._tuple_brackets: dict[str, str] = enabled_flags.get("TUPLE_BRACKETS", {"(": ")"})
        # Complex flags
        # Bytes flags
        self._bytes_encoding: str = enabled_flags.get("BYTES_ENCODING", "utf-8")
        # Bool flags
        self._bool_toggle_value: bool = enabled_flags.get("BOOL_TOGGLE_VALUE", True)

        self.parsers: dict[type[E], NativeParserFragment[E]] = dict()
        for type_, parser in self._parser_fragments.items():
            parser_flags = self._get_parser_flags(type_)
            self.parsers[type_] = parser(**parser_flags)  # Wrapped so this all works okay! (Needs to happen after the flags are set)

    def _get_parser_flags(self, parser_for_type: type) -> dict[str, _ty.Any]:
        """Extract parser-fragment-specific constructor flags.

        :param parser_for_type: Target fragment base type.
        :return: Mapping of matching fragment options.
        """
        parser_name: str = parser_for_type.__name__
        params_dict: dict[str, _ty.Any] = dict()
        for v, k in self.__dict__.items():
            if v.startswith("_" + parser_name) and v != parser_name and not isinstance(k, _ts.FunctionType):
                params_dict[v.removeprefix("_" + parser_name + "_")] = k
        return params_dict

    @staticmethod
    def _parse_string(stream: TokenStream, delimiter: str) -> str:
        """Read a quoted string (including delimiters) from the stream.

        :param stream: Input stream positioned at the opening delimiter.
        :param delimiter: Delimiter character to match.
        :return: Parsed quoted token.
        """
        string: str = ""
        delimiters_seen: int = 0
        while token := stream.consume():
            string += token
            if token == delimiter:  # Add token to output
                delimiters_seen += 1
            if delimiters_seen == 2:
                break
        return string

    @staticmethod
    def _parse_bracket(stream: TokenStream, start_bracket: str) -> str:
        """Read a balanced bracket block from the stream.

        :param stream: Input stream positioned at opening bracket.
        :param start_bracket: Opening bracket character.
        :return: Parsed bracketed token including delimiters.
        """
        end_bracket: str | None = {"(": ")", "[": "]", "{": "}", "<": ">"}.get(start_bracket)
        if end_bracket is None:
            raise ValueError(f"Unknown start bracket '{start_bracket}'.")
        string: str = ""
        currently_opened: int = 1
        while token := stream.consume():
            if token == end_bracket:
                currently_opened -= 1
            elif token == start_bracket:
                currently_opened += 1
            string += token
            if currently_opened == 0:
                break
        return string

    def _parse_argname(self, stream: TokenStream) -> str | ArgumentParsingError:
        """Parse argument name token after ``-``/``--``.

        :param stream: Token stream.
        :return: Parsed argument name or parsing error.
        """
        argument_name: str = ""
        skip_next: bool = False
        while token := stream.consume():
            if skip_next:
                skip_next = False
                argument_name += token
            elif token == "\\":
                skip_next = True
            elif token == " ":
                if argument_name == "":
                    return ArgumentParsingError("The argument name is not allowed to be empty.",
                                                ParsingErrorSeverity.CAN_CONTINUE, stream.copy())
                stream.reverse()
                break
            elif token in self._arg_assignment_tokens:
                if argument_name == "":
                    return ArgumentParsingError("The argument name is not allowed to be empty.",
                                                ParsingErrorSeverity.CAN_CONTINUE, stream.copy())
                stream.reverse()
                break
            elif token in self._argname_valid:
                argument_name += token
            elif token in ('"', "'") and argument_name == "":  # String only valid if it isn't like this myval's
                stream.reverse()
                argument_name = self._parse_string(stream, delimiter=token)
                next_token = stream.consume()
                if next_token is not None and next_token not in " " + self._arg_assignment_tokens:
                    return ArgumentParsingError("You cannot have a non delimiting token next to the end of a "
                                                "string.", ParsingErrorSeverity.SKIP_TO_NEXT_SPACE, stream.copy())
                elif next_token is None:
                    break
                stream.reverse()
                break
            else:  # token invalid
                return ArgumentParsingError(f"Invalid token '{token}' in argument name",
                                            ParsingErrorSeverity.CAN_CONTINUE, stream.copy())
        return argument_name

    def _skip_to_argval(self, stream: TokenStream) -> None | ArgumentParsingError:
        """Consume separators between argument name and value.

        :param stream: Token stream.
        :return: ``None`` on success, or parsing error.
        """
        had_assignment_token: bool = False
        spaces: int = 0
        while token := stream.consume():
            if token == " ":
                if spaces == 0 and not had_assignment_token:
                    spaces += 1
                elif spaces == 1 and had_assignment_token:
                    spaces += 1
                else:
                    return ArgumentParsingError("The argument value is not allowed to be empty, if you want to "
                                                "pass an empty string please use string delimiters.",
                                                ParsingErrorSeverity.CAN_CONTINUE, stream.copy())
                pass
            elif token in self._arg_assignment_tokens:
                if had_assignment_token:
                    return ArgumentParsingError(f"It is not allowed to have two assignment tokens "
                                                f"({self._arg_assignment_tokens}) between argument name and value.",
                                                ParsingErrorSeverity.CAN_CONTINUE, stream.copy())  # Two assignment token e.g. := or == or :: or : : or : =
                had_assignment_token = True
                spaces = 1
            else:
                stream.reverse()
                break
        return None

    def _parse_full_argument(self, argument_name: str, stream: TokenStream) -> tuple[str, str] | ArgumentParsingError:
        """Parse a complete ``name=value`` pair from stream context.

        :param argument_name: Pre-parsed name, or empty to parse from stream.
        :param stream: Token stream.
        :return: ``(name, value)`` pair or parsing error.
        """
        if not argument_name:
            argument_name: str = self._parse_argname(stream)
        error: ArgumentParsingError | None = self._skip_to_argval(stream)
        if error:
            return error
        argument_value: str = ""
        skip_next: bool = False
        # last_space: bool = False  # TODO: Will only be possible in NO_POSITIONAL_ARGS

        while token := stream.consume():
            if skip_next:
                skip_next = False
                argument_value += token
            elif token == "\\":
                skip_next = True
            elif token == " ":
            #     last_space = Tru
                break
            # elif token == "-":
            #     ...
            elif token in ('"', "'") and argument_value == "":  # String only valid if it isn't like this myval's
                stream.reverse()
                argument_value = self._parse_string(stream, delimiter=token)
                next_token = stream.consume()
                if next_token is not None and next_token not in " ":
                    return ArgumentParsingError("You cannot have a non delimiting token next to the end of a "
                                                "string.", ParsingErrorSeverity.SKIP_TO_NEXT_SPACE, stream.copy())
                elif next_token is None:
                    break
                stream.reverse()
                break
            else:
                # last_space = False
                argument_value += token

        if not argument_value:
            return ArgumentParsingError("The argument value is not allowed to be empty, if you want to pass an "
                                        "empty string please use string delimiters.", ParsingErrorSeverity.CAN_CONTINUE,
                                        stream.copy())
        return argument_name, argument_value

    def _parse_letters(self, stream: TokenStream) -> str | ArgumentParsingError:
        """Parse combined short boolean flag letters.

        :param stream: Token stream.
        :return: Parsed short-letter sequence or parsing error.
        """
        letters: str = ""
        while token := stream.consume():
            if token == " ":
                break
            elif token in "-" + self._arg_assignment_tokens:
                return ArgumentParsingError(f"It is not allowed to have a value token "
                                            f"(-{self._arg_assignment_tokens}) next to a boolean flag.",
                                            ParsingErrorSeverity.SKIP_TO_NEXT_SPACE, stream.copy())
            else:
                letters += token
        return letters

    @staticmethod
    def _defuse_error(replacement_value: _ty.Any, possible_error: _ty.Any | ArgumentParsingError, stream: TokenStream,
                      error_lst: list[ArgumentParsingError]) -> _ty.Any | ArgumentParsingError:
        """Collect parser errors and continue with fallback value.

        :param replacement_value: Value returned when ``possible_error`` is an error.
        :param possible_error: Candidate parsed value or parsing error.
        :param stream: Token stream for recovery movement.
        :param error_lst: Mutable error sink list.
        :return: Parsed value or fallback replacement.
        """
        if not isinstance(possible_error, ArgumentParsingError):
            return possible_error
        # possible_error.raise_()  # TODO: Handled the high severity error right? (stop parsing)
        if possible_error.severity == ParsingErrorSeverity.SKIP_TO_NEXT_SPACE:
            while token := stream.consume():
                if token == " ":
                    break
        elif possible_error.severity == ParsingErrorSeverity.REACHED_INVALID_STATE:
            while _ := stream.consume():
                ...
        error_lst.append(possible_error)
        return replacement_value

    def list_known_flags(self) -> dict[str, type[_ty.Any]]:
        """Discover runtime-supported flag names and their value types.

        :return: Flag-name/type mapping.
        """
        flags_dict: dict[str, type[_ty.Any]] = dict()
        for v, k in self.__dict__.items():
            if v.startswith("_") and v not in {"parsers"} and not isinstance(k, _ts.FunctionType):
                flag_name: str = v[1:].upper()
                flags_dict[flag_name] = _ty.get_type_hints(NativeParserEnabledFlags).get(flag_name) or type(k)
        return flags_dict

    def explain_flag(self, flag_name: str) -> str:
        """Return a human-readable explanation for one parser flag.

        :param flag_name: Flag to explain.
        :return: Description string.
        :raises ValueError: If flag is unknown.
        """
        explanations: dict[str, str] = {
            "PARSER_FRAGMENTS": "Override or extend parser fragment classes used for value parsing.",
            "NO_POSITIONAL_ARGS": "Disallow positional arguments entirely (currently not implemented).",
            "SMART_TYPING": "Enable smart typing heuristics (currently not implemented).",
            "ALLOW_NON_DETERMINISTIC_BEHAVIOUR": "Allow non-deterministic parsing branches.",
            "ARGNAME_VALID": "Characters allowed in argument names.",
            "ARG_ASSIGNMENT_TOKENS": "Characters accepted between argument names and values.",
            "ERROR_IF_TOO_MANY_KWARGS": "Raise on unknown keyword-style arguments when enabled.",
            "IGNORE_VALUE_PARSING_ERROR_BELOW": "Ignore value-parsing errors below this severity.",
            "RETURN_ALL_POSONLY_AS_KWARG": "Return positional-only parsed values in kwargs.",
            "PARSE_PYTHON_TYPES": "Global default for Python-literal-like parsing behavior.",
            "STR_PARSE_PYTHON_TYPES": "Enable quoted-string unwrapping for string parsing.",
            "STR_DELIMITERS": "Delimiter characters used for string parsing.",
            "ITERABLE_PARSE_PYTHON_TYPES": "Enable bracket-aware iterable parsing.",
            "ITERABLE_ERROR_IF_UNSURE": "Emit uncertainty errors for ambiguous iterable parsing.",
            "ITERABLE_CONVERT_TO_TYPE": "Container type used for parsed iterable values.",
            "ITERABLE_ASSIGNMENT_TOKENS": "Assignment-token set used while parsing iterable entries.",
            "ITERABLE_BRACKETS": "Bracket pairs recognized for iterable literals.",
            "LIST_PARSE_PYTHON_TYPES": "Enable bracket-aware list parsing.",
            "LIST_ERROR_IF_UNSURE": "Emit uncertainty errors for ambiguous list parsing.",
            "LIST_ASSIGNMENT_TOKENS": "Assignment-token set used while parsing list entries.",
            "LIST_BRACKETS": "Bracket pairs recognized for list literals.",
            "DICT_PARSE_PYTHON_TYPES": "Enable bracket-aware dict parsing.",
            "DICT_LIST_SEPARATORS": "Separators used between dictionary items.",
            "DICT_KV_SEPARATORS": "Separators used between dictionary keys and values.",
            "DICT_IGNORE_RANDOM_SEPARATORS": "Ignore unexpected separators in dictionary parsing.",
            "DICT_ALLOW_SAME_K_AND_V_SEPARATORS": "Allow the same separator token for pairs and key/value.",
            "DICT_ASSIGNMENT_TOKENS": "Assignment-token set used while parsing dictionaries.",
            "DICT_BRACKETS": "Bracket pairs recognized for dictionary literals.",
            "SET_PARSE_PYTHON_TYPES": "Enable bracket-aware set parsing.",
            "SET_ERROR_IF_UNSURE": "Emit uncertainty errors for ambiguous set parsing.",
            "SET_ASSIGNMENT_TOKENS": "Assignment-token set used while parsing sets.",
            "SET_BRACKETS": "Bracket pairs recognized for set literals.",
            "TUPLE_PARSE_PYTHON_TYPES": "Enable bracket-aware tuple parsing.",
            "TUPLE_ERROR_IF_UNSURE": "Emit uncertainty errors for ambiguous tuple parsing.",
            "TUPLE_ASSIGNMENT_TOKENS": "Assignment-token set used while parsing tuples.",
            "TUPLE_BRACKETS": "Bracket pairs recognized for tuple literals.",
            "BYTES_ENCODING": "Encoding used to convert textual bytes input.",
            "BOOL_TOGGLE_VALUE": "Toggle boolean values on repeated flag occurrences.",
        }
        key = flag_name.strip().upper()
        known_flags = self.list_known_flags()
        if key not in known_flags:
            raise ValueError(f"Unknown flag '{flag_name}'. Known flags: {', '.join(sorted(known_flags))}")
        return explanations.get(key, "No additional documentation is available for this flag.")

    # TODO: Easy to switch out ArgumentParsers and ArgumentValueParsers (For no_positional_args and similar)
    # TODO: Flag bool letters as letter strings vs arguments with one - and longer names
    def parse_args(self, args: list[str], arguments: list[Argument], endpoint_path: str
                   ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """Parse CLI tokens against endpoint argument definitions.

        :param args: Raw CLI token list.
        :param arguments: Argument metadata for target endpoint.
        :param endpoint_path: Endpoint identifier used in diagnostics.
        :return: Parsed ``(positionals, kwargs)``.
        :raises ArgumentParsingError: On unrecoverable parse failures.
        """
        bool_arg_names: list[str] = list()
        is_reference_to: dict[str, str] = dict()
        for arg in arguments:
            if bool == arg.type:
                bool_arg_names.extend([arg.metavar] + arg.alternative_names + ([arg.letter] if arg.letter else []))
            elif arg.broken_type.base_type == _ty.Union and bool in arg.broken_type.arguments and not self._no_positional_args:
                raise ArgumentParsingError(f"Under the NativeParser having a boolean argument that can also be another "
                                    f"type is not allowed. This is to make it possible to have the converting "
                                    f"process be a DFA Automaton. Basically for every token there must be a known "
                                    f"transition. There cannot be multiple which would be the case for boolean "
                                    f"arguments that can also be other types.")
            for name in [arg.metavar] + arg.alternative_names + ([arg.letter] if arg.letter else []):
                is_reference_to[name] = arg.metavar

        arg_str: str = " ".join(args)
        stream = TokenStream(arg_str)

        posarg_values: list[str] = list()
        curr_pos_arg: str = ""
        kwarg_values: dict[str, list[str]] = defaultdict(list)
        errors: list[ArgumentParsingError] = list()
        skip_next: bool = False

        while token := stream.consume():
            if skip_next:
                skip_next = False
                curr_pos_arg += token
            elif token == "\\":
                skip_next = True
            elif token == "-":
                if curr_pos_arg != "":
                    posarg_values.append(curr_pos_arg)
                    curr_pos_arg = ""
                next_token = stream.consume()
                if next_token is None:
                    self._defuse_error(None, ArgumentParsingError(
                        "You cannot have an argument name delimiter without an argument name.",
                        ParsingErrorSeverity.REACHED_INVALID_STATE, stream.copy()), stream, errors)
                elif next_token == "-":  # Get arg name and potential value
                    name: str | None = self._defuse_error(None, self._parse_argname(stream), stream, errors)
                    if name is None:  # Error was already logged and handled, we can continue
                        continue
                    elif name not in is_reference_to:
                        if not self._error_if_too_many_kwargs:
                            is_reference_to[name] = name
                        else:
                            errors.append(ArgumentParsingError(f"There is no argument with the name '{name}'.",
                                                               stream=stream.copy()))
                            continue
                    if name in bool_arg_names:
                        kwarg_values[name].append("")
                    else:
                        (_, value) = self._defuse_error((None, None),
                                                        self._parse_full_argument(name, stream), stream, errors)
                        if value is None:  # Error was already logged and handled, we can continue
                            continue
                        kwarg_values[is_reference_to[name]].append(value)
                else:
                    stream.reverse()
                    if next_token in bool_arg_names:
                        parsed_letters = self._defuse_error("", self._parse_letters(stream), stream, errors)
                        for letter in parsed_letters:
                            if letter not in bool_arg_names:
                                errors.append(ArgumentParsingError(f"The letter '{letter}' is not a boolean argument and was in a letter string.", stream=stream.copy()))
                                continue
                            kwarg_values[is_reference_to[letter]].append("")  # We already know letter exists as its in bool_arg_names
                    else:
                        name: str | None = self._defuse_error(None, self._parse_argname(stream), stream, errors)
                        if name is None:  # Error was already logged and handled, we can continue
                            continue
                        elif name not in is_reference_to:
                            if not self._error_if_too_many_kwargs:
                                is_reference_to[name] = name
                            else:
                                errors.append(ArgumentParsingError(f"There is no argument with the name '{name}'.",
                                                                   stream=stream.copy()))
                                continue
                        elif len(name) != 1:
                            self._defuse_error(None, ArgumentParsingError("The length of the letter argument was exceeded.",
                                                                          ParsingErrorSeverity.SKIP_TO_NEXT_SPACE, stream.copy()), stream, errors)
                            continue
                        (_, value) = self._defuse_error((None, None),
                                                        self._parse_full_argument(name, stream), stream, errors)
                        if value is None:  # Error was already logged and handled, we can continue
                            continue
                        kwarg_values[is_reference_to[name]].append(value)
            elif token == " ":
                if curr_pos_arg != "":
                    posarg_values.append(curr_pos_arg)
                    curr_pos_arg = ""
            elif token in ('"', "'") and curr_pos_arg == "":  # String only valid if it isn't like this myval's
                stream.reverse()
                curr_pos_arg = self._parse_string(stream, delimiter=token)
                posarg_values.append(curr_pos_arg)
                curr_pos_arg = ""  # Reset the argument, we do not want to fuse together strings e.g. : "abc" a should be two args and not "abca"
                next_token = stream.consume()
                if next_token is not None and next_token not in " ":
                    self._defuse_error(None, ArgumentParsingError("You cannot have a non delimiting "
                                                                  "token next to the end of a string.",
                                                                  ParsingErrorSeverity.SKIP_TO_NEXT_SPACE,
                                                                  stream.copy()), stream, errors)
                elif next_token is None:
                    break
                stream.reverse()
            elif token in ("(", "[", "{", "<") and curr_pos_arg == "":
                stream.reverse()
                curr_pos_arg = self._parse_bracket(stream, token)
                next_token = stream.consume()
                if next_token is not None and next_token not in " ,":
                    self._defuse_error(None, ArgumentParsingError(
                        "You cannot have a non delimiting token next to the end of a string.",
                        ParsingErrorSeverity.SKIP_TO_NEXT_SPACE, stream.copy()), stream, errors)
                elif next_token is None:
                    break
                stream.reverse()
            elif token in self._arg_assignment_tokens:
                self._defuse_error(None, ArgumentParsingError("Assignment token without an "
                                                             "argument name and value are not allowed.",
                                                             ParsingErrorSeverity.SKIP_TO_NEXT_SPACE, stream.copy()),
                                  stream, errors)
            else:
                curr_pos_arg += token

        if curr_pos_arg != "":
            posarg_values.append(curr_pos_arg)
            curr_pos_arg = ""

        if errors:
            wording: str = "was an error" if len(errors) == 1 else "were errors"
            output: str = f"There {wording} during the parsing of the arguments for the endpoint '{endpoint_path}':\n\n"
            for i, error in enumerate(errors, 1):
                output += f"{i}. {error.message}\n"
                output += f"   > index: {error.stream.get_index()}\n"
                output += f"   > input: {error.show()}\n"
            raise ValueError(output)
            print(output)
            return list(), dict()

        # print(posarg_values, letters, kwarg_values, bool_arg_names)

        value_errors: list[ValueParsingError | ArgumentParsingError] = list()

        _SENTINEL = object()
        def _walk_value_type(composite_type: BrokenType, v: _ty.Any,
                             outside_value_errors: list[ArgumentParsingError] | None = None, last_failed: bool = False,
                             ) -> _ty.Any | ArgumentParsingError:
            """Recursively parse one value against a (possibly nested) type tree.

            :param composite_type: Current expected type node.
            :param v: Raw candidate value or token list.
            :param outside_value_errors: Optional external error sink.
            :param last_failed: Whether the previous type branch failed.
            :return: Parsed value, parsing error, or sentinel.
            """
            fragment = self.parsers.get(composite_type.base_type)
            if fragment is None:
                return _SENTINEL
            parsed_v: _ty.Any = self._defuse_error(_SENTINEL, fragment.parse(v, last_failed), TokenStream(""),
                                                   value_errors if outside_value_errors is None else outside_value_errors)
            if parsed_v is _SENTINEL:
                return _SENTINEL
            if composite_type.arguments:
                finished: list[tuple[_ty.Any, _ty.Any]] = list()
                local_value_errors: list[ArgumentParsingError] = list()
                for composite in fragment.iter(parsed_v, composite_type):
                    identifier, s, types = composite
                    is_parsed: bool = False
                    for type_ in types:
                        p = _walk_value_type(type_, s if isinstance(s, list) else [s], local_value_errors)
                        if p is not _SENTINEL:
                            finished.append((identifier, p))
                            is_parsed = True
                            break
                    if not is_parsed:
                        finished.append((identifier, s))
                        (value_errors if outside_value_errors is None else outside_value_errors).extend(local_value_errors)  # Expose type errors
                        self._defuse_error(None, ArgumentParsingError(f"Could not parse '{s}'."), TokenStream(""),
                                           value_errors if outside_value_errors is None else outside_value_errors)
                        return _SENTINEL
                if fragment.REPLACE:
                    parsed_v = [x[1] for x in finished] if len(finished) > 1 else finished[0][1]
                elif fragment.REPLACE_WITH_SET:
                    parsed_v = fragment.set(parsed_v, finished)
                else:
                    fragment.set(parsed_v, finished)
            return parsed_v

        parsed_posargs: list[_ty.Any] = list()
        parsed_kwargs: dict[str, _ty.Any] = dict()
        if self._allow_non_deterministic_behaviour:
            argument_distribution_errors: list[ValueParsingError] = list()  # We do not need a new type internally
            trying_numbers: dict[Argument, tuple[int, int]] = {
                k: (k.nargs.spec.n, k.nargs.spec.n - len(kwarg_values[k.metavar]) if k.nargs.spec.n is not None else 0)
                for k in arguments}
            for arg, (curr, i) in trying_numbers.copy().items():
                while i < 0:
                    if arg.nargs.is_lower_max(curr):
                        curr += 1
                        i += 1
                        trying_numbers[arg] = (curr, i)
                    else:
                        argument_distribution_errors.append(
                            ValueParsingError("There were too many keyword arguments for an argument.", arg))
                        break

            last_none: Argument | None = None
            for k, (curr, used) in trying_numbers.items():
                if curr is None:
                    last_none = k
            if last_none is not None:
                trying_numbers[last_none] = (len(posarg_values), len(posarg_values))

            loop_n: int = 0
            while True:
                difference: int = sum(x[1] for x in trying_numbers.values()) - len(posarg_values)
                changed: bool = False

                if difference == 0:
                    break
                elif difference < 0:  # Increase capture
                    remaining_diff: int = abs(difference)
                    for arg, (curr, i) in reversed(trying_numbers.copy().items()):
                        while remaining_diff > 0:
                            if arg.nargs.is_lower_max(curr) and not arg.kwarg_only:
                                changed = True
                                curr += 1
                                i += 1
                                remaining_diff -= 1
                                trying_numbers[arg] = (curr, i)
                            else:
                                break
                elif difference > 0:  # Decrease capture
                    remaining_diff: int = abs(difference)
                    for arg, (curr, i) in reversed(trying_numbers.copy().items()):
                        while remaining_diff > 0 and i > 0:
                            if (arg.nargs.is_higher_min(curr) and (not arg.nargs.spec.n is None or loop_n == 1)) or (
                                    not arg.required and loop_n == 1):
                                changed = True
                                curr -= 1
                                i -= 1
                                remaining_diff -= 1
                                trying_numbers[arg] = (curr, i)
                            else:
                                break

                if not changed and loop_n > 1:  # Minimum possible difference reached
                    wording: str = "were" if abs(difference) > 1 else "was"
                    if difference < 0:
                        argument_distribution_errors.append(ValueParsingError(
                            f"There {wording} {abs(difference)} positional arguments too much ({posarg_values}).",
                            None))
                    else:
                        argument_distribution_errors.append(ValueParsingError(
                            f"There {wording} {abs(difference)} arguments too few ({posarg_values}, {kwarg_values}).",
                            None))
                    break
                loop_n += 1
            # print("TryNum", trying_numbers)

            # TODO: Improve error handling / output specificity when dealing with too few arguments. (Which argument, etc.)
            # TODO: Maybe go through current trying_numbers and list out what argument cannot be reduced / cannot be expanded for too few or too many.
            if argument_distribution_errors:
                wording: str = "was an error" if len(argument_distribution_errors) == 1 else "were errors"
                output: str = f"There {wording} during the distribution of the arguments for the endpoint '{endpoint_path}':\n\n"
                for i, error in enumerate(argument_distribution_errors, 1):
                    output += f"{i}. {error.message}\n"
                    if error.argument:
                        output += f"   > Name: {error.argument.metavar}\n"
                        output += f"   > NArgs: MIN_MAX({error.argument.nargs.min}, {error.argument.nargs.max})\n"
                        output += f"   > NArgsSpec N: {error.argument.nargs.spec.n}\n"
                raise ValueError(output)
                print(output)
                return list(), dict()

            last_n: int = 0
            for arg in arguments:
                parsed_strings: list[str] = kwarg_values.pop(arg.metavar, [])
                wanted_n: int = trying_numbers[arg][1]
                wanted_posargs: list[str] = posarg_values[last_n:last_n+wanted_n]
                last_n += wanted_n

                if len(parsed_strings) == 0 and len(wanted_posargs) == 0:
                    if not isinstance(arg.default, NoDefault):
                        parsed_kwargs[arg.name] = arg.default
                        continue
                    elif arg.required:  # Shouldn't ever happen but better safe than sorry for now!
                        value_errors.append(ValueParsingError("Required argument did not receive a value.", arg, None,
                                                              ValueParsingSeverity.REQUIRED))
                        continue
                    else:
                        continue

                severity: ValueParsingSeverity = ValueParsingSeverity.REQUIRED_ARG if arg.required else ValueParsingSeverity.NOT_REQUIRED_ARG
                caught_parsing_errors: list[ArgumentParsingError] = list()

                parsed: _ty.Any = _SENTINEL
                for i in range(2):  # Have a max of 2 parsing rounds
                    parsed = _walk_value_type(arg.broken_type, wanted_posargs + parsed_strings,
                                                       caught_parsing_errors, i==1)

                    if parsed is _SENTINEL:  # Argument parsed checker
                        continue
                    else:
                        break

                if parsed is _SENTINEL:  # Parsing failed completely
                    value_errors.append(
                        ValueParsingError(f"The value {wanted_posargs + parsed_strings} of an argument could not be parsed to it's type.", arg,
                                          caught_parsing_errors, severity))
                    continue

                if arg.broken_type.base_type == bool and arg.default:  # Do the final transformation for the arguments here
                    parsed = arg.default and not parsed

                if arg.positional_only and len(parsed_strings) > 0:  # Argument value checkers
                    value_errors.append(ValueParsingError("Positional only argument was passed a keyword value.", arg, None, severity))
                    continue
                elif arg.checking_func is not None:
                    ret: _ty.Any | ArgumentParsingError = arg.checking_func(arg, parsed)
                    if isinstance(ret, ArgumentParsingError):
                        value_errors.append(ValueParsingError("The checking func of an argument failed.", arg, [ret], severity))
                        continue
                    parsed = ret
                elif len(arg.choices) > 0 and parsed not in arg.choices:
                    value_errors.append(ValueParsingError(f"Keyword value '{parsed}' for an argument is not in its choices.", arg, None, severity))
                    continue

                if arg.positional_only and not self._return_all_posonly_as_kwarg:
                    parsed_posargs.append(parsed)
                else:
                    parsed_kwargs[arg.name] = parsed
            parsed_kwargs.update(kwarg_values)
        else:
            def _get(from_: list, index: int) -> _ty.Any:
                """Pop one element from ``from_`` if available.

                :param from_: Source list.
                :param index: Index to pop.
                :return: Popped value or ``None``.
                """
                if len(from_) > 0:
                    return from_.pop(index)
                return None

            posarg_values.reverse()
            for arg in arguments:
                print(arg.nargs.max, arg.nargs.min)
                if arg.nargs.spec.n is None:  #  or (arg.nargs.min != arg.nargs.max and not (arg.nargs.min == 0 and arg.nargs.max == 1))
                    # Every NativeParserFragment consumes 1 to n command line arguments, but maximally 1 positional argument.
                    # The current implementation of *args and **kwargs is unfinished and sloppy.
                    # For every arg => We get all Kwargs then we look at the positionals and fill the args up.
                    #   => If at the end positionals remain, we try to adjust our "how many args for this one" assumptions.
                    #   => If not possible we exit the loop and declare this a success.
                    raise NotImplementedError(f"Non deterministic nargs are not set to allowed.")
                parsed_strings: list[str] = kwarg_values.pop(arg.metavar, [])

                if parsed_strings:
                    severity: ValueParsingSeverity = ValueParsingSeverity.REQUIRED_ARG if arg.required else ValueParsingSeverity.NOT_REQUIRED_ARG

                    if arg.nargs.min-len(parsed_strings) > 0 and arg.kwarg_only:
                        value_errors.append(ValueParsingError("Keyword only argument was passed a positional value.", arg, None, severity))
                        continue
                    elif len(parsed_strings) > arg.nargs.spec.n:
                        value_errors.append(ValueParsingError("Argument received too many keyword arguments.", arg, None, severity))
                        continue
                    errored_while_getting_posargs: bool = False
                    for _ in range(max(0, arg.nargs.min-len(parsed_strings))):
                        gotten_posarg: str | None = _get(posarg_values, -1)
                        if gotten_posarg is None:
                            value_errors.append(ValueParsingError("Argument did not get enough arguments to satisfy it's nargs requirement.", arg, None, severity))
                            errored_while_getting_posargs = True
                            break
                        parsed_strings.insert(0, gotten_posarg)  # TODO: Make more efficient
                    if errored_while_getting_posargs:
                        continue

                    caught_parsing_errors: list[ArgumentParsingError] = list()

                    parsed: _ty.Any = _SENTINEL
                    for i in range(2):  # Have a max of 2 parsing rounds
                        parsed = _walk_value_type(arg.broken_type, parsed_strings,
                                                           caught_parsing_errors, i == 1)

                        if parsed is _SENTINEL:  # Argument parsed checker
                            continue
                        else:
                            break

                    if parsed is _SENTINEL:  # Parsing failed completely
                        value_errors.append(ValueParsingError("The keyword value of an argument could not be parsed to it's type.", arg, caught_parsing_errors, severity))
                        continue

                    if arg.broken_type.base_type == bool and arg.default:  # Do the final transformation for the arguments here
                        parsed = arg.default and not parsed

                    if arg.positional_only:  # Argument value checkers
                        value_errors.append(ValueParsingError("Positional only argument was passed a keyword value.", arg, None, severity))
                        continue
                    elif arg.checking_func is not None:
                        ret: _ty.Any | ArgumentParsingError = arg.checking_func(arg, parsed)
                        if isinstance(ret, ArgumentParsingError):
                            value_errors.append(ValueParsingError("The checking func of an argument failed.", arg, [ret], severity))
                            continue
                        parsed = ret
                    elif len(arg.choices) > 0 and parsed not in arg.choices:
                        value_errors.append(ValueParsingError(f"Keyword value '{parsed}' for an argument is not in its choices.", arg, None, severity))
                        continue

                    parsed_kwargs[arg.name] = parsed
                elif arg.broken_type.base_type != bool and (posarg := _get(posarg_values, -1)):
                    if arg.broken_type.base_type == bool:
                        posarg_values.append(posarg)
                        if arg.required:
                            value_errors.append(ValueParsingError("Required boolean argument did not receive a value.", arg, None, ValueParsingSeverity.REQUIRED))
                        continue
                    severity: ValueParsingSeverity = ValueParsingSeverity.REQUIRED_POS if arg.required else ValueParsingSeverity.NOT_REQUIRED_POS

                    gotten_posargs: list[str] = [posarg]
                    errored_while_getting_posargs: bool = False
                    for _ in range(max(0, arg.nargs.min-1)):
                        gotten_posarg: str | None = _get(posarg_values, -1)
                        if gotten_posarg is None:
                            value_errors.append(ValueParsingError("Argument did not get enough arguments to satisfy it's nargs requirement.", arg, None, severity))
                            errored_while_getting_posargs = True
                            break
                        gotten_posargs.append(gotten_posarg)
                    if errored_while_getting_posargs:
                        continue

                    caught_parsing_errors: list[ArgumentParsingError] = list()

                    parsed_pos: _ty.Any = _SENTINEL
                    for i in range(2):  # Have a max of 2 parsing rounds
                        parsed_pos = _walk_value_type(arg.broken_type, gotten_posargs,
                                                           caught_parsing_errors, i == 1)

                        if parsed_pos is _SENTINEL:  # Argument parsed checker
                            continue
                        else:
                            break

                    if parsed_pos is _SENTINEL:  # Parsing failed completely
                        value_errors.append(ValueParsingError("The positional value of an argument could not be parsed to it's type.", arg, caught_parsing_errors, severity))
                        continue

                    # Do the final transformations for the arguments here

                    if arg.kwarg_only:
                        value_errors.append(ValueParsingError("Keyword only argument was passed a positional value.", arg, None, severity))
                        continue
                    elif arg.checking_func is not None:
                        ret: _ty.Any | ArgumentParsingError = arg.checking_func(arg, parsed_pos)
                        if isinstance(ret, ArgumentParsingError):
                            value_errors.append(ValueParsingError("The checking func of an argument failed.", arg, [ret], severity))
                            continue
                        parsed_pos = ret
                    elif len(arg.choices) > 0 and parsed_pos not in arg.choices:
                        value_errors.append(ValueParsingError(f"Chosen value '{parsed_pos}' for an argument is not in its choices.", arg, None, severity))
                        continue

                    if arg.positional_only and not self._return_all_posonly_as_kwarg:
                        parsed_posargs.append(parsed_pos)
                    else:
                        parsed_kwargs[arg.name] = parsed_pos
                elif not isinstance(arg.default, NoDefault):
                    parsed_kwargs[arg.name] = arg.default
                elif arg.required and arg.nargs.min != 0:
                    value_errors.append(ValueParsingError("Required argument did not receive a value.", arg, None, ValueParsingSeverity.REQUIRED))
                    continue

            if len(posarg_values) != 0:
                value_errors.append(ValueParsingError(f"There were too many positional arguments ({posarg_values}).", None))
            # if len(kwarg_values) != 0 and self._error_if_too_many_kwargs:  # Already handeled by argument parsing now
            #     value_errors.append(ValueParsingError(f"There were unknown named arguments ({dict(kwarg_values)}).", None))
            # else:
            parsed_kwargs.update(kwarg_values)

        if [x for x in value_errors if not x.severity < self._ignore_value_parsing_error_below]:
            wording: str = "was an error" if len(value_errors) == 1 else "were errors"
            output: str = f"There {wording} during the parsing of the arguments for the endpoint '{endpoint_path}':\n\n"
            for i, error in enumerate(value_errors, 1):
                output += f"{i}. {error.message}" + (" [IGNORED]" if error.severity < self._ignore_value_parsing_error_below else "") + "\n"
                if error.argument:
                    output += f"   > Name: {error.argument.metavar}\n"
                    output += f"   > Type: {pretty_type(error.argument.type)}\n"
                    output += f"   > Choices: {error.argument.choices}\n"
                    output += f"   > Required: {error.argument.required}\n"
                if error.parsing_errors:
                    inner_wording: str = "was an error" if len(error.parsing_errors) == 1 else "were errors"
                    output += f"\n   There {inner_wording} during the parsing of the arguments for the argument:\n\n"
                    for j, parsing_error in enumerate(error.parsing_errors, 1):
                        output += f"   {j}. {parsing_error.message}\n"
                        output += f"      > index: {parsing_error.stream.get_index()}\n"
                        output += f"      > input: {parsing_error.show()}\n"
            raise ValueError(output)
            print(output)
            return list(), dict()
        return parsed_posargs, parsed_kwargs
