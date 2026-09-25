"""Read the package name from an APK's binary AndroidManifest.xml (stdlib only, no aapt).

droidforge must know which package an install creates BEFORE it installs, so the step can declare what it touches
(P10) and carry its undo (P2)."""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path
from typing import List, Optional

RES_XML, STRING_POOL, START_ELEMENT = 0x0003, 0x0001, 0x0102
UTF8_FLAG = 1 << 8


class ApkError(Exception):
    pass


def _strings(buf: bytes, off: int) -> List[str]:
    _, hsize, _ = struct.unpack_from("<HHI", buf, off)
    count, _styles, flags, start, _ = struct.unpack_from("<IIIII", buf, off + 8)
    offsets = struct.unpack_from(f"<{count}I", buf, off + hsize)
    base = off + start
    out = []
    for o in offsets:
        p = base + o
        if flags & UTF8_FLAG:
            n = buf[p + 1]  # byte length (short strings), after the char length byte
            p += 2
            if buf[p - 1] & 0x80:
                n = ((buf[p - 1] & 0x7F) << 8) | buf[p]
                p += 1
            out.append(buf[p:p + n].decode("utf-8", "replace"))
        else:
            n = struct.unpack_from("<H", buf, p)[0]
            out.append(buf[p + 2:p + 2 + 2 * n].decode("utf-16-le", "replace"))
    return out


def manifest_package(axml: bytes) -> str:
    if len(axml) < 8 or struct.unpack_from("<H", axml, 0)[0] != RES_XML:
        raise ApkError("not a binary AndroidManifest.xml")
    off = struct.unpack_from("<H", axml, 2)[0]
    strings: List[str] = []
    while off + 8 <= len(axml):
        ctype, _hsize, size = struct.unpack_from("<HHI", axml, off)
        if size < 8:
            break
        if ctype == STRING_POOL:
            strings = _strings(axml, off)
        elif ctype == START_ELEMENT:
            name_idx = struct.unpack_from("<I", axml, off + 20)[0]
            attr_start, attr_size, attr_count = struct.unpack_from("<HHH", axml, off + 24)
            if strings and strings[name_idx] == "manifest":
                for i in range(attr_count):
                    a = off + 16 + attr_start + i * attr_size
                    _ns, name, raw = struct.unpack_from("<III", axml, a)
                    if strings[name] == "package" and raw != 0xFFFFFFFF:
                        return strings[raw]
                raise ApkError("manifest has no package attribute")
        off += size
    raise ApkError("no <manifest> element")


def package_name(apk: Path) -> str:
    try:
        with zipfile.ZipFile(apk) as z:
            return manifest_package(z.read("AndroidManifest.xml"))
    except (zipfile.BadZipFile, KeyError, struct.error) as e:
        raise ApkError(f"{apk}: cannot read the package name ({e})") from e


def split_name(apk: Path) -> Optional[str]:
    """The `split` attribute is not needed: a split has the same package as its base; the base is the one
    whose file name does not start with split_ / config."""
    n = apk.name
    return n if n.startswith(("split_", "config.")) else None
