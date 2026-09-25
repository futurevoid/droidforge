"""App names (the label shown above the package name in Settings > Apps) - read-only, stdlib only.

Android has no shell command that prints an app's label, so droidforge reads it from the app's own APK:
`<application android:label>` in the binary AndroidManifest.xml, resolved through resources.arsc (English
preferred, then the default language). Both files are streamed with `unzip -p <apk> <file> | base64` (Android's
own ziptool; nothing is written on the phone) and the result is cached per APK path, so an app is only read
again after it is updated. A label that lives in a framework / ROM resource package cannot be resolved here and
is shown as unknown ("").
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import struct
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

RES_XML, STRING_POOL, RES_TABLE, XML_RESOURCE_MAP = 0x0003, 0x0001, 0x0002, 0x0180
START_ELEMENT, TABLE_PACKAGE, TABLE_TYPE = 0x0102, 0x0200, 0x0201
UTF8_FLAG = 1 << 8
ATTR_LABEL = 0x01010001            # android:label
TYPE_REFERENCE, TYPE_STRING = 0x01, 0x03
NO_ENTRY = 0xFFFFFFFF
FLAG_SPARSE, FLAG_OFFSET16 = 0x01, 0x02          # ResTable_type flags
ENTRY_COMPLEX, ENTRY_COMPACT = 0x0001, 0x0008    # ResTable_entry flags
APK_PATH = r"/[A-Za-z0-9_./~=+\-]+\.apk"
MAX_LABEL = 80


class LabelError(Exception):
    pass


# ---------------------------------------------------------------------- string pools
def _len8(buf: bytes, p: int) -> Tuple[int, int]:
    n = buf[p]
    if n & 0x80:
        return ((n & 0x7F) << 8) | buf[p + 1], p + 2
    return n, p + 1


def pool_string(buf: bytes, off: int, idx: int) -> str:
    """String `idx` of the ResStringPool chunk at `off` (decoded lazily: resource pools can be large)."""
    _, hsize, _ = struct.unpack_from("<HHI", buf, off)
    count, _styles, flags, start, _ = struct.unpack_from("<IIIII", buf, off + 8)
    if not 0 <= idx < count:
        raise LabelError(f"string index {idx} outside the pool ({count})")
    p = off + start + struct.unpack_from("<I", buf, off + hsize + 4 * idx)[0]
    if flags & UTF8_FLAG:
        _chars, p = _len8(buf, p)
        n, p = _len8(buf, p)
        return buf[p:p + n].decode("utf-8", "replace")
    n = struct.unpack_from("<H", buf, p)[0]
    p += 2
    if n & 0x8000:
        n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", buf, p)[0]
        p += 2
    return buf[p:p + 2 * n].decode("utf-16-le", "replace")


# ---------------------------------------------------------------------- manifest
def manifest_label(axml: bytes) -> Tuple[Optional[str], Optional[int]]:
    """(literal label, resource id) of <application android:label>; (None, None) when there is none."""
    if len(axml) < 8 or struct.unpack_from("<H", axml, 0)[0] != RES_XML:
        raise LabelError("not a binary AndroidManifest.xml")
    off = struct.unpack_from("<H", axml, 2)[0]
    pool = -1
    resmap: List[int] = []
    while off + 8 <= len(axml):
        ctype, hsize, size = struct.unpack_from("<HHI", axml, off)
        if size < 8:
            break
        if ctype == STRING_POOL:
            pool = off
        elif ctype == XML_RESOURCE_MAP:
            resmap = list(struct.unpack_from(f"<{(size - hsize) // 4}I", axml, off + hsize))
        elif ctype == START_ELEMENT and pool >= 0:
            name_idx = struct.unpack_from("<I", axml, off + 20)[0]
            if pool_string(axml, pool, name_idx) == "application":
                attr_start, attr_size, attr_count = struct.unpack_from("<HHH", axml, off + 24)
                for i in range(attr_count):
                    a = off + 16 + attr_start + i * attr_size
                    _ns, name, raw, _vsize, _res0, dtype, data = struct.unpack_from("<IIIHBBI", axml, a)
                    is_label = (name < len(resmap) and resmap[name] == ATTR_LABEL) or \
                        (not resmap and pool_string(axml, pool, name) == "label")
                    if not is_label:
                        continue
                    if dtype == TYPE_REFERENCE:
                        return None, data
                    if dtype == TYPE_STRING:
                        return pool_string(axml, pool, raw if raw != NO_ENTRY else data), None
                    return None, None
                return None, None
        off += size
    raise LabelError("no <application> element")


# ---------------------------------------------------------------------- resources.arsc
def _config_rank(buf: bytes, cfg: int) -> int:
    """Lower is better: English (US / no country) < other English < default < anything else."""
    lang, country = buf[cfg + 8:cfg + 10], buf[cfg + 10:cfg + 12]
    if lang == b"en":
        return 0 if country in (b"\x00\x00", b"US") else 1
    return 2 if lang == b"\x00\x00" else 3


def _type_entry(buf: bytes, off: int, hsize: int, entry: int) -> Optional[int]:
    """Absolute offset of entry `entry` in the ResTable_type chunk at `off`, None if absent."""
    flags = buf[off + 9]
    count, entries_start = struct.unpack_from("<II", buf, off + 12)
    idx = off + hsize
    if flags & FLAG_SPARSE:
        for i in range(count):
            e, rel = struct.unpack_from("<HH", buf, idx + 4 * i)
            if e == entry:
                return off + entries_start + rel * 4
            if e > entry:
                return None
        return None
    if entry >= count:
        return None
    if flags & FLAG_OFFSET16:
        rel = struct.unpack_from("<H", buf, idx + 2 * entry)[0]
        return None if rel == 0xFFFF else off + entries_start + rel * 4
    rel = struct.unpack_from("<I", buf, idx + 4 * entry)[0]
    return None if rel == NO_ENTRY else off + entries_start + rel


def _entry_value(buf: bytes, p: int) -> Optional[Tuple[int, int]]:
    """(dataType, data) of a simple entry; None for a complex (bag) entry."""
    size, flags = struct.unpack_from("<HH", buf, p)
    if flags & ENTRY_COMPACT:
        return flags >> 8, struct.unpack_from("<I", buf, p + 4)[0]
    if flags & ENTRY_COMPLEX:
        return None
    _vsize, _res0, dtype, data = struct.unpack_from("<HBBI", buf, p + size)
    return dtype, data


def resolve(arsc: bytes, res_id: int, hops: int = 5) -> Optional[str]:
    """The string resource `res_id` from resources.arsc (best locale), following references. None if the id
    belongs to another resource package (framework / ROM) or is not a string."""
    if len(arsc) < 12 or struct.unpack_from("<H", arsc, 0)[0] != RES_TABLE:
        raise LabelError("not a resources.arsc")
    pkg_id, type_id, entry = res_id >> 24, (res_id >> 16) & 0xFF, res_id & 0xFFFF
    off = struct.unpack_from("<H", arsc, 2)[0]
    pool = -1
    best: Optional[Tuple[int, int, int]] = None      # (rank, dtype, data)
    while off + 8 <= len(arsc):
        ctype, hsize, size = struct.unpack_from("<HHI", arsc, off)
        if size < 8:
            break
        if ctype == STRING_POOL and pool < 0:
            pool = off
        elif ctype == TABLE_PACKAGE:
            pid = struct.unpack_from("<I", arsc, off + 8)[0]
            if pid in (pkg_id, 0):
                sub = off + hsize
                while sub + 8 <= off + size:
                    stype, shsize, ssize = struct.unpack_from("<HHI", arsc, sub)
                    if ssize < 8:
                        break
                    if stype == TABLE_TYPE and arsc[sub + 8] == type_id:
                        p = _type_entry(arsc, sub, shsize, entry)
                        val = _entry_value(arsc, p) if p is not None else None
                        if val is not None:
                            rank = _config_rank(arsc, sub + 20)
                            if best is None or rank < best[0]:
                                best = (rank, val[0], val[1])
                    sub += ssize
        off += size
    if best is None:
        return None
    _, dtype, data = best
    if dtype == TYPE_STRING and pool >= 0:
        return pool_string(arsc, pool, data)
    if dtype == TYPE_REFERENCE and hops > 0 and data >> 24 == pkg_id:
        return resolve(arsc, data, hops - 1)
    return None


def label_from(axml: bytes, arsc: Optional[bytes]) -> Optional[str]:
    literal, res_id = manifest_label(axml)
    if literal is not None:
        return literal
    if res_id is None or arsc is None:
        return None
    return resolve(arsc, res_id)


def clean(label: Optional[str]) -> str:
    """One printable line (labels are shown in tables and the CLI)."""
    if not label:
        return ""
    s = " ".join(label.split())
    return s[:MAX_LABEL]


# ---------------------------------------------------------------------- device
def apk_paths(device: "Device") -> Dict[str, str]:
    """{package: base APK path} from `pm list packages -f -u` (one call for every package)."""
    out: Dict[str, str] = {}
    for line in device.out("pm list packages -f -u").splitlines():
        m = re.match(r"\s*package:(\S+\.apk)=(\S+)\s*$", line)
        if m:
            out[m.group(2)] = m.group(1)
    return out


def unzip_cmd(path: str, member: str) -> str:
    if not re.fullmatch(APK_PATH, path):
        raise LabelError(f"unexpected APK path {path!r}")
    return f"unzip -p '{path}' {member} | base64"


def _fetch(device: "Device", path: str, member: str) -> Optional[bytes]:
    try:
        cmd = unzip_cmd(path, member)
    except LabelError:
        return None
    r = device.read(cmd, timeout=60)
    if not r.ok or not r.out.strip():
        return None
    try:
        return base64.b64decode("".join(r.out.split()), validate=True)
    except (binascii.Error, ValueError):
        return None


def read_label(device: "Device", path: str) -> str:
    """The label of the APK at `path` on the phone ("" if it cannot be read)."""
    axml = _fetch(device, path, "AndroidManifest.xml")
    if not axml:
        return ""
    try:
        literal, res_id = manifest_label(axml)
        if literal is not None:
            return clean(literal)
        if res_id is None or res_id >> 24 != 0x7F:
            return ""
        arsc = _fetch(device, path, "resources.arsc")
        return clean(resolve(arsc, res_id)) if arsc else ""
    except (LabelError, struct.error, IndexError):
        return ""


class LabelCache:
    """{package: (apk path, label)} per phone, kept on disk so each APK is read once per version."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path
        self.data: Dict[str, List[str]] = {}
        if path is not None and path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self.data = {k: v for k, v in raw.items() if isinstance(v, list) and len(v) == 2}
            except (OSError, ValueError):
                self.data = {}

    @classmethod
    def for_device(cls, device: "Device") -> "LabelCache":
        from droidforge import config
        serial = re.sub(r"[^A-Za-z0-9_.-]", "_", device.serial or "device")
        return cls(config.paths().sub("cache") / f"labels-{serial}.json")

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1, sort_keys=True), encoding="utf-8")
        except OSError:
            pass

    def lookup(self, device: "Device", pkgs: Iterable[str]) -> Dict[str, str]:
        """{package: label} for `pkgs` ("" when unknown). Reads only APKs that are new or changed."""
        wanted = list(dict.fromkeys(p for p in pkgs if p))
        if not wanted:
            return {}
        paths = apk_paths(device)
        todo = [p for p in wanted if p in paths and self.data.get(p, ["", ""])[0] != paths[p]]
        for i, p in enumerate(todo, 1):
            if len(todo) > 10 and (i == 1 or i % 25 == 0):
                device.log.info(f"Reading app names: {i}/{len(todo)}")
            self.data[p] = [paths[p], read_label(device, paths[p])]
        if todo:
            self.save()
        return {p: self.data[p][1] for p in wanted if p in self.data and self.data[p][1]}


def lookup(device: "Device", pkgs: Iterable[str]) -> Dict[str, str]:
    """{package: label} with the on-disk cache for this phone. Never raises: names are a display aid."""
    try:
        cache = getattr(device, "_labels", None)
        if cache is None:
            cache = LabelCache.for_device(device)
            device._labels = cache  # type: ignore[attr-defined]
        return cache.lookup(device, pkgs)
    except Exception as e:  # noqa: BLE001 - a missing name must never stop a plan or a list
        device.log.trace(f"app names unavailable: {e}", 2)
        return {}
