"""Signer check (R-8.2): group packages by signing-certificate digest; label the groups by reference packages -
`android` = platform, `com.google.android.gms` = Google, a known OPPO / realme app = OEM, the rest third-party /
unknown. Read-only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from droidforge.features.audit.perms import AppAudit

OEM_REFERENCES = ("com.heytap.market", "com.oplus.camera", "com.coloros.filemanager", "com.oplus.safecenter",
                  "com.coloros.gallery3d")


@dataclass
class SignerGroup:
    digest: str
    label: str
    packages: List[str] = field(default_factory=list)


def group(apps: List[AppAudit]) -> List[SignerGroup]:
    by: Dict[str, List[str]] = {}
    for a in apps:
        by.setdefault(a.signer or "(unknown)", []).append(a.package)
    ref = {a.package: a.signer for a in apps}
    labels = {}
    if ref.get("android"):
        labels[ref["android"]] = "platform (signed like the OS)"
    if ref.get("com.google.android.gms"):
        labels.setdefault(ref["com.google.android.gms"], "Google")
    for p in OEM_REFERENCES:
        if ref.get(p):
            labels.setdefault(ref[p], "OEM (OPPO / realme / OnePlus)")
            break
    groups = [SignerGroup(d, labels.get(d, "third-party / unknown"), sorted(pk)) for d, pk in by.items()]
    order = {"platform (signed like the OS)": 0, "OEM (OPPO / realme / OnePlus)": 1, "Google": 2}
    return sorted(groups, key=lambda g: (order.get(g.label, 3), -len(g.packages)))
