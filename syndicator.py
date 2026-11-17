"""Read the Lua data written by Syndicator without executing it."""

from dataclasses import dataclass, field
from decimal import Decimal
import re


TOKEN = re.compile(
    r'(?P<skip>\s+|--\[\[.*?\]\]|--[^\r\n]*)'
    r'|(?P<string>"(?:\\(?:\r\n|[\s\S])|[^"\\\r\n])*"|\x27(?:\\(?:\r\n|[\s\S])|[^\x27\\\r\n])*\x27)'
    r'|(?P<number>-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)'
    r'|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<symbol>[{}\[\]=,;])',
    re.DOTALL,
)
ESCAPE = re.compile(r"\\(?:(\d{1,3})|(\r\n|[\s\S]))")
ESCAPES = dict(zip("abfnrtv", "\a\b\f\n\r\t\v"))
ESCAPES.update({"\\": "\\", '"': '"', "'": "'", "\n": "\n", "\r\n": "\n"})


def decode_string(token):
    def replace(match):
        digits, char = match.groups()
        if digits is not None and int(digits) <= 255:
            return chr(int(digits))
        if char in ESCAPES:
            return ESCAPES[char]
        raise ValueError(f"Unsupported Lua escape {match[0]!r}")

    return ESCAPE.sub(replace, token[1:-1])


@dataclass
class Node:
    kind: str
    value: object
    start: int
    end: int
    entries: dict = field(default_factory=dict)

    def table(self):
        if self.kind != "table":
            raise ValueError("Expected a Lua table")
        return self.entries

class Parser:
    def __init__(self, source):
        self.source = source
        self.position = 0
        self.advance()

    def advance(self):
        while self.position < len(self.source):
            match = TOKEN.match(self.source, self.position)
            if match is None:
                raise ValueError(f"Unsupported Lua syntax at offset {self.position}")
            self.position = match.end()
            if match.lastgroup != "skip":
                self.token = match
                return
        self.token = None

    def is_token(self, value):
        return self.token is not None and self.token[0] == value

    def take(self, value=None, kind=None):
        token = self.token
        if token is None or (value is not None and token[0] != value) or (
            kind is not None and token.lastgroup != kind
        ):
            raise ValueError(f"Expected {value or kind or 'value'} at offset {self.position}")
        self.advance()
        return token

    def document(self):
        globals_ = {}
        while self.token is not None:
            name = self.take(kind="name")[0]
            self.take("=")
            if name in globals_:
                raise ValueError(f"Duplicate global {name}")
            globals_[name] = self.value()
            if self.is_token(";"):
                self.take(";")
        return globals_

    def value(self):
        token = self.take()
        kind, literal = token.lastgroup, token[0]
        if literal == "{":
            entries = {}
            index = 1
            while not self.is_token("}"):
                if self.is_token("["):
                    self.take("[")
                    key_node = self.value()
                    if key_node.kind not in ("string", "number", "boolean"):
                        raise ValueError("Unsupported Lua table key")
                    key = key_node.kind, key_node.value
                    self.take("]")
                    self.take("=")
                else:
                    key = "number", Decimal(index)
                    index += 1
                if key in entries:
                    raise ValueError(f"Duplicate Lua table key {key[1]!r}")
                entries[key] = self.value()
                if self.is_token(",") or self.is_token(";"):
                    self.take()
                elif not self.is_token("}"):
                    raise ValueError("Expected a Lua table field separator")
            closing = self.take("}")
            return Node("table", None, token.start(), closing.end(), entries)
        if kind == "string":
            value = decode_string(literal)
        elif kind == "number":
            value = Decimal(literal)
        elif literal in ("true", "false"):
            kind, value = "boolean", literal == "true"
        elif literal == "nil":
            kind, value = "nil", None
        else:
            raise ValueError(f"Unsupported Lua value {literal!r}")
        return Node(kind, value, token.start(), token.end())


def field_at(node, name):
    return node.table()["string", name]


def read_characters(raw):
    # Lua strings can contain byte escapes. Decode labels as UTF-8 after parsing.
    data = Parser(raw.decode("latin-1")).document()["SYNDICATOR_DATA"]
    version = field_at(data, "Version")
    if version.kind != "number" or version.value != 2:
        raise ValueError("Expected Syndicator data version 2.")
    return field_at(data, "Characters").table()
