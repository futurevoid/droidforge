"""HTML session report (R-11.4): one standalone file (stdlib only, inline CSS) - device, health, what changed, what
failed, audit results, undo hints. Everything is read from history / probes; nothing is written to the phone."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from droidforge import __version__
from droidforge.engine import health

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device
    from droidforge.engine.history import Entry, History

CSS = """
:root { --bg:#fff; --fg:#1b1b1b; --muted:#666; --ok:#1a7f37; --bad:#c62828; --warn:#9a6700; --line:#ddd; }
@media (prefers-color-scheme: dark) { :root { --bg:#111; --fg:#e8e8e8; --muted:#999; --ok:#3fb950; --bad:#f85149;
  --warn:#d29922; --line:#333; } }
body { background:var(--bg); color:var(--fg); font:14px/1.45 system-ui, sans-serif; margin:24px auto;
  max-width:1100px; padding:0 16px; }
h1 { font-size:22px; } h2 { font-size:17px; margin-top:28px; border-bottom:1px solid var(--line); }
table { border-collapse:collapse; width:100%; } td, th { text-align:left; padding:4px 8px;
  border-bottom:1px solid var(--line); vertical-align:top; } code { font-size:12px; word-break:break-all; }
.ok { color:var(--ok); } .bad { color:var(--bad); font-weight:600; } .warn { color:var(--warn); }
.muted { color:var(--muted); }
"""


def _e(x: object) -> str:
    return html.escape(str(x))


def _entries(history: "History", since: str) -> List["Entry"]:
    return [e for e in history.entries() if e.ts >= since]


def build(device: "Device", history: "History", since: str = "", with_audit: bool = False) -> str:
    h = health.run(device)
    es = _entries(history, since)
    changed = [e for e in es if e.ok and not e.dry_run]
    failed = [e for e in es if not e.ok and not e.dry_run]
    stamp = f"{datetime.now():%Y-%m-%d %H:%M}"
    out = [f"<!doctype html><html lang=en><head><meta charset=utf-8><title>droidforge report</title>"
           f"<style>{CSS}</style></head><body>",
           f"<h1>droidforge report</h1><p class=muted>{_e(stamp)} - droidforge "
           f"{_e(__version__)}</p>",
           "<h2>Device</h2><table>",
           f"<tr><th>Phone</th><td>{_e(device.label)} ({_e(device.serial)})</td></tr>",
           f"<tr><th>Build</th><td><code>{_e(device.fingerprint)}</code></td></tr>",
           f"<tr><th>Android / SDK</th><td>{_e(device.getprop('ro.build.version.release'))} / {device.sdk}</td></tr>",
           f"<tr><th>Covers</th><td>{_e(since.replace('T', ' ')[:19]) if since else 'all history'}</td></tr>",
           "</table>", "<h2>Health now</h2><table>"]
    for p in h.probes.values():
        cls, mark = {True: ("ok", "ok"), False: ("bad", "FAIL"), None: ("warn", "unknown")}[p.ok]
        out.append(f"<tr><td class={cls}>{mark}</td><td>{_e(p.label)}</td><td><code>{_e(p.value or '-')}</code>"
                   f"{(' - ' + _e(p.detail)) if p.detail else ''}</td></tr>")
    out.append("</table>")
    if h.failing:
        out.append("<p class=bad>Something is wrong. In this order:</p><ol>"
                   + "".join(f"<li>{_e(a[3:])}</li>" for a in health.advice(
                       [health.Regression(p.name, p.label, '', p.value, p.detail) for p in h.failing])) + "</ol>")
    out.append(f"<h2>What changed ({len(changed)})</h2>")
    out.append(_table(changed, undo=True) if changed else "<p class=muted>Nothing.</p>")
    out.append(f"<h2>What failed ({len(failed)})</h2>")
    out.append(_table(failed, undo=False) if failed else "<p class=muted>Nothing.</p>")
    if with_audit:
        out.append(_audit(device))
    out.append("<h2>Undo</h2><ul>"
               "<li>One change: <code>droidforge undo &lt;id&gt;</code> (TUI: Backup &amp; History &gt; Undo selected)"
               "</li><li>Everything since a point: <code>droidforge rollback &lt;id&gt;</code></li>"
               "<li>If the phone misbehaves and droidforge's undo does not help: Settings &gt; Reset all settings "
               "(keeps apps and data).</li></ul></body></html>")
    return "\n".join(out)


def _table(entries: List["Entry"], undo: bool) -> str:
    rows = ["<table><tr><th>time</th><th>id</th><th>what</th><th>command</th><th>" + ("undo" if undo else "output")
            + "</th></tr>"]
    for e in entries:
        last = ("undone" if e.undone else "<br>".join(f"<code>{_e(u)}</code>" for u in e.undo) or "manual - none") \
            if undo else f"<code>{_e(e.out_tail[-300:])}</code>"
        rows.append(f"<tr><td>{_e(e.ts.replace('T', ' ')[:19])}</td><td><code>{_e(e.id)}</code></td>"
                    f"<td>{_e(e.label)}</td><td><code>{_e(e.cmd)}</code></td><td>{last}</td></tr>")
    return "\n".join(rows + ["</table>"])


def _audit(device: "Device") -> str:
    from droidforge.features.audit import net, perms, signers
    apps = perms.scan(device)
    user = [a for a in apps if not a.system]
    out = [f"<h2>Audit: permissions of your apps ({len(user)})</h2><table>"]
    for a in user:
        if a.granted or a.ops:
            out.append(f"<tr><td>{_e(a.package)}</td><td>{_e(', '.join(p.rsplit('.', 1)[-1] for p in a.granted))}"
                       f"</td><td>{_e(', '.join(a.ops))}</td></tr>")
    out.append("</table><h2>Audit: signers</h2><table>")
    for g in signers.group(apps):
        out.append(f"<tr><td>{_e(g.label)}</td><td><code>{_e(g.digest[:16])}</code></td><td>{len(g.packages)}</td></tr>")
    rep = net.scan(device)
    out.append(f"</table><h2>Audit: live connections ({len(rep.conns)})</h2>")
    out.append(f"<p class=warn>{_e(rep.note)}</p>" if rep.note else "")
    out.append("<table>" + "".join(f"<tr><td>{_e(c.proto)}</td><td>{_e(c.remote)}</td><td>{_e(c.state)}</td>"
                                   f"<td>{_e(', '.join(c.apps) or c.uid)}</td></tr>" for c in rep.conns) + "</table>")
    return "\n".join(out)


def write(device: "Device", history: "History", since: str = "", with_audit: bool = False,
          directory: Optional[Path] = None) -> Path:
    if directory is None:
        from droidforge import config
        directory = config.paths().sub("reports")
    path = Path(directory) / f"{(device.serial or 'device').replace(':', '_')}-{datetime.now():%Y%m%d-%H%M%S}.html"
    path.write_text(build(device, history, since, with_audit), encoding="utf-8")
    return path
