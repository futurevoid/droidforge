# droidforge - ColorOS package map

## Never touched outside expert mode (R-4.3, R-4.3b) - also never language targets (P12)

UI infrastructure, hidden from lists by default:
`android`, `oplus`, every package matching `*overlay*`, `*.rro*`, `*auto_generated_characteristics_rro`,
`android.frameworkres.overlay*`, `com.android.internal.display.cutout.*`, `com.android.internal.systemui.navbar.*`,
`com.android.theme.*`, `com.oplus.uxdesign`, `com.oplus.uiengine`, `com.oplus.systemui.plugins`,
`com.oplus.framework.*`, `com.oplus.blur`, `com.oplus.wallpapers`, `com.heytap.colorfulengine`,
`com.android.settings*`, `com.android.permissioncontroller`, `com.oplus.securitypermission`,
`com.oplus.keyguard.*`, `com.oplus.aod`.
Owner's device (2026-09-25) has these present; the list is matched by pattern at runtime.

Per-app language (R-3.2) targets exclude, in addition: every package in `pm list packages -s`, the current IME and
launcher, and all packages above.


Source of truth for `droidforge/data/packages.py`. Tiers are UAD-NG ratings (fetched 2026-09-25).
Package names vary between OPPO / OnePlus / realme and between China and global ROMs: every preset is
**filtered to installed packages** at runtime. Phase 9 adds the real Neo 8 China list
(`tests/data/neo8_cn_packages.txt`, from `adb shell pm list packages -f -u`) and the sim seed is updated from it.

## Telemetry preset (R-5.1)

| Package | UAD | What |
|---|---|---|
| com.oplus.statistics.rom | Recommended | User Experience Program, runs at boot |
| com.nearme.statistics.rom | Recommended | User Experience Program (older name) |
| com.nearme.deamon | Recommended | keeps statistics.rom alive |
| com.oplus.crashbox | Recommended | crash data upload |
| com.oplus.logkit / com.coloros.logkit / com.oppo.logkit | Recommended | log + bug-report tooling |
| com.oppo.logkitservice / com.oppo.logkitsdservice / com.coloros.logkit.plugin.upload | Recommended | log upload |
| com.oplus.onetrace | Recommended | logging component |
| com.oplus.locationproxy | Recommended | carrier location telemetry (not GPS) |
| com.heytap.openid | Recommended | OAID / ad identifiers |
| com.oplus.powermonitor / com.oppo.oppopowermonitor | Recommended | thermal/power log upload |
| com.oplus.ocloud | Recommended | logs |
| com.coloros.feedback | Recommended | feedback service |
| com.coloros.remoteguardservice | Recommended | statistics (China only) |
| com.coloros.sauhelper / com.oplus.sauhelper | Recommended | statistics placeholder (may refuse disable) |
| com.coloros.regservice | Recommended | DM registration |
| com.coloros.prome.service | Recommended | feedback/smart touch framework |
| com.oplus.cosa | **Advanced** | "App enhancement" - contacts OPPO servers on each app launch; opt-in row |

## Ads / promos (R-5.4)

| Target | Packages | Action |
|---|---|---|
| Lock-screen magazine | com.heytap.pictorial (Recommended) | disable. **Never** com.coloros.pictorial (Unsafe: lock-screen settings break) - it is locked |
| System push promos | com.heytap.mcs, com.coloros.mcs (Recommended) | disable |
| Store/theme/game/browser notifications | com.heytap.market, com.oppo.market, com.heytap.themestore, com.nearme.themestore, com.oplus.themestore, com.nearme.gamecenter, com.heytap.browser, com.nearme.browser | `pm revoke <pkg> android.permission.POST_NOTIFICATIONS` + app-op `POST_NOTIFICATION ignore`. Stores/browser may be disabled if the user prefers; **theme stores are never disabled** (theme apply depends on them - P9b) |
| Launcher suggestions | com.opos.cs "Hot Apps" (Recommended), com.heytap.quicksearchbox, com.oppo.quicksearchbox (Recommended), com.nearme.instant.platform, com.oppo.instant.local.service (Recommended) | disable |
| -1 screen feed | com.coloros.assistantscreen (Advanced) | disable (removes the shelf left of home) |

## Install hijack (R-5.3)

| Package | UAD | Note |
|---|---|---|
| com.oplus.appdetail | Recommended | "Secure app installation" - the ColorOS install-scan screen |
| com.heytap.market / com.oppo.market | Recommended | store taking over installs; notifications off at minimum |

## Keep-list (R-4.4) - warn, excluded from bulk selections

- Game space: com.coloros.gamespace, com.coloros.gamespaceui, com.oplus.games, com.oplus.stdid (GameSpace dependency)
- Smart sidebar: com.coloros.smartsidebar (+ any installed package containing `smartsidebar`)

## OTA path (updates are ALLOWED - never in presets; warn if selected manually)

com.oplus.ota, com.oppo.ota, com.oplus.sau, com.coloros.sau, com.oplus.romupdate, com.nearme.romupdate,
com.oplus.cota, com.heytap.appplatform (Unsafe), com.oplus.appplatform (Unsafe), com.coloros.simsettings

## Telephony - never disabled by swaps (R-6.2); locked in debloat

com.android.phone, com.android.contacts (ColorOS dialer lives here), com.android.incallui, com.android.mms,
com.android.providers.telephony, com.android.server.telecom, any `*.ims*`

## Locked = expert mode + typed package name (R-4.3)

Pattern list carried over from legacy `HARD_PROTECTED`: `systemui`, `com.android.phone`, `telephony`, `.ims`,
`com.android.settings`, `permissioncontroller`, `packageinstaller`, `com.android.shell`, `keyguard`,
`com.google.android.gms`, `com.google.android.gsf`, `com.android.vending`, `webview`, `networkstack`, `framework`
+ the current IME + the current launcher + every UAD `Unsafe` package (e.g. com.coloros.safecenter,
com.oplus.safecenter, com.coloros.pictorial).
Guarded (`I UNDERSTAND`): legacy `FALLBACK_PROTECTED` patterns for packages UAD does not know.

## ColorOS secure keyboard (R-3.4) - remove for user 0 (owner request: "totally extinguish")

| Package | UAD | Note |
|---|---|---|
| com.oplus.securitykeyboard | Recommended | pops up on password fields; `ime disable` its IME ids, force-stop, `pm uninstall --user 0` (no `-k`), fallback disable-user |
| com.coloros.securitykeyboard | Recommended | older name, same handling |
| com.oplus.onet | Recommended | framework the secure keyboard uses; optional |

Root mode (R-10.2) can hide the APK systemlessly.

## Chinese IMEs (R-3.4)

Patterns: `sogou`, `sohu`, `baidu`, `iflytek`, `qqpinyin`, `tencent`, `pinyin`, `oplus.inputmethod`,
`coloros.inputmethod`, `heytap`.

## Default swaps (R-6.2)

| Function | ColorOS (keep enabled unless noted) | Replacement | Role |
|---|---|---|---|
| Browser | com.heytap.browser / com.nearme.browser (may disable, Recommended) | org.mozilla.fenix (Firefox Nightly) | android.app.role.BROWSER |
| Gallery | com.coloros.gallery3d (Advanced; optional disable + camera-thumbnail warning) | com.google.android.apps.photos | - |
| Files | com.coloros.filemanager (Advanced; optional disable) | com.google.android.apps.nbu.files | - |
| SMS | com.android.mms (never disable) | com.google.android.apps.messaging | android.app.role.SMS |
| Dialer | com.android.contacts (never disable) | com.google.android.dialer | android.app.role.DIALER |
| Calendar | com.coloros.calendar | com.google.android.calendar | - |
| Contacts | com.android.contacts (never disable) | com.google.android.contacts | - |
| Notes | com.coloros.note / com.oplus.note | com.google.android.keep | - |

## App catalog (presets.py)

| App | Package | Sources |
|---|---|---|
| Gboard | com.google.android.inputmethod.latin | Play |
| Firefox Nightly | org.mozilla.fenix | Play; official Mozilla APK (URL: VERIFY in P4) |
| Google Photos / Files / Messages / Phone / Calendar / Contacts / Keep | see table above | Play |
| Shizuku | moe.shizuku.privileged.api | GitHub releases RikkaApps/Shizuku; Play |
| Play Integrity checker | gr.nikolasspyr.integritycheck (VERIFY) | Play |
| Tasker / SystemUI Tuner / Automate / MacroDroid (power-perm presets) | net.dinglisch.android.taskerm / com.zacharee1.systemuituner / com.llamalab.automate / com.arlosoft.macrodroid | presets apply only if installed |
