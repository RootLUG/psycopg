"""
Dict to hstore adaptation
"""

# Copyright (C) 2021 The Psycopg Team

import re
from typing import Dict, List, Optional, Type

from .. import pq
from .. import errors as e
from .. import postgres
from ..abc import Buffer, AdaptContext
from ..adapt import PyFormat, RecursiveDumper, RecursiveLoader
from ..postgres import TEXT_OID
from .._typeinfo import TypeInfo

_re_escape = re.compile(r'(["\\])')
_re_unescape = re.compile(r"\\(.)")

_re_hstore = re.compile(
    r"""
    # hstore key:
    # a string of normal or escaped chars
    "((?: [^"\\] | \\. )*)"
    \s*=>\s* # hstore value
    (?:
        NULL # the value can be null - not caught
        # or a quoted string like the key
        | "((?: [^"\\] | \\. )*)"
    )
    (?:\s*,\s*|$) # pairs separated by comma or end of string.
""",
    re.VERBOSE,
)


Hstore = Dict[str, Optional[str]]


class BaseHstoreDumper(RecursiveDumper):

    format = pq.Format.TEXT

    def dump(self, obj: Hstore) -> bytes:
        if not obj:
            return b""

        tokens: List[str] = []

        def add_token(s: str) -> None:
            tokens.append('"')
            tokens.append(_re_escape.sub(r"\\\1", s))
            tokens.append('"')

        for k, v in obj.items():

            if not isinstance(k, str):
                raise e.DataError("hstore keys can only be strings")
            add_token(k)

            tokens.append("=>")

            if v is None:
                tokens.append("NULL")
            elif not isinstance(v, str):
                raise e.DataError("hstore keys can only be strings")
            else:
                add_token(v)

            tokens.append(",")

        del tokens[-1]
        data = "".join(tokens)
        dumper = self._tx.get_dumper(data, PyFormat.TEXT)
        return dumper.dump(data)


class HstoreLoader(RecursiveLoader):

    format = pq.Format.TEXT

    def load(self, data: Buffer) -> Hstore:
        loader = self._tx.get_loader(TEXT_OID, self.format)
        s: str = loader.load(data)

        rv: Hstore = {}
        start = 0
        for m in _re_hstore.finditer(s):
            if m is None or m.start() != start:
                raise e.DataError(f"error parsing hstore pair at char {start}")
            k = _re_unescape.sub(r"\1", m.group(1))
            v = m.group(2)
            if v is not None:
                v = _re_unescape.sub(r"\1", v)

            rv[k] = v
            start = m.end()

        if start < len(s):
            raise e.DataError(
                f"error parsing hstore: unparsed data after char {start}"
            )

        return rv


def register_hstore(
    info: TypeInfo, context: Optional[AdaptContext] = None
) -> None:

    info.register(context)

    adapters = context.adapters if context else postgres.adapters

    # Generate and register a customized text dumper
    dumper: Type[BaseHstoreDumper] = type(
        "HstoreDumper", (BaseHstoreDumper,), {"_oid": info.oid}
    )
    adapters.register_dumper(dict, dumper)

    # register the text loader on the oid
    adapters.register_loader(info.oid, HstoreLoader)
