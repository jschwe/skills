# ohos-uitest — CLI reference (`hdc shell uitest …`)

Long-form companion to SKILL.md. Each subsection gives the full flag
set with examples for one CLI subcommand. All commands assume the
device is reachable via `hdc list targets`.

## `screenCap` — capture a screenshot

| Flag | Arg | Default | Notes |
|---|---|---|---|
| `-p` | `<savePath>` | `/data/local/tmp/<timestamp>.png` | Path **must** be under `/data/local/tmp/`. |
| `-d` | `<displayId>` | default display | API 20+. Query IDs via `hidumper`. |

```sh
hdc shell uitest screenCap                              # default path
hdc shell uitest screenCap -p /data/local/tmp/now.png   # explicit
hdc shell uitest screenCap -d 0                          # specific display
hdc file recv /data/local/tmp/now.png ./now.png         # pull to host
```

Inside ArkTS test code, `driver.screenCap(path, displayId?)` /
`driver.screenCapture(path, rect)` must use the app sandbox path
(`/data/storage/el2/base/cache/...`), not `/data/local/tmp/` — the
test HAP runs at APL `normal` and can't write outside its sandbox.

## `dumpLayout` — export the component tree

| Flag | Arg | Notes |
|---|---|---|
| `-p` | `<savePath>` | Must be under `/data/local/tmp/`. Default name: `<timestamp>.json`. |
| `-i` | — | Disable filtering of invisible components and window merging. Mutually exclusive with `-a`. |
| `-a` | — | Include `BackgroundColor`, `Content`, `FontColor`, `FontSize`, `extraAttrs`. Mutually exclusive with `-i`. |
| `-b` | `<bundleName>` | Restrict to one app's window. |
| `-w` | `<windowId>` | Restrict to a single window (find IDs via `hidumper -s WindowManagerService -a -a`). |
| `-m` | `<true\|false>` | Merge multiple windows into one tree. Default `true`. |
| `-d` | `<displayId>` | API 20+. |

```sh
hdc shell uitest dumpLayout -p /data/local/tmp/layout.json
hdc shell uitest dumpLayout -b com.example.app -p /data/local/tmp/app.json
hdc shell uitest dumpLayout -a -p /data/local/tmp/full.json
hdc file recv /data/local/tmp/layout.json ./layout.json
```

The output JSON is a tree. Each node carries `attributes` (text, type,
id, bounds, etc.) and `children`. Useful as a one-shot "find me the
coordinates / matchers I need" before scripting `uiInput` or writing
ArkTS `ON.…` matchers.

## `uiInput` — inject UI events

Subcommand list (each below has its own arg signature):

```
click | doubleClick | longClick | swipe | drag | fling | dircFling
inputText | text | keyEvent | help
```

### `click` / `doubleClick` / `longClick`

```sh
hdc shell uitest uiInput click       <x> <y>
hdc shell uitest uiInput doubleClick <x> <y>
hdc shell uitest uiInput longClick   <x> <y>
```

### `swipe` / `drag`

| Pos | Arg | Required | Notes |
|---|---|---|---|
| 1 | `from_x` | yes | start coordinate |
| 2 | `from_y` | yes | |
| 3 | `to_x`   | yes | end coordinate |
| 4 | `to_y`   | yes | |
| 5 | `velocity` | no | px/s, range 200–40000, default 600 |

```sh
hdc shell uitest uiInput swipe 100 1500 100 500 800
hdc shell uitest uiInput drag 200 600 800 600 600
```

`drag` differs from `swipe` in that it triggers a long-press first, so
draggable items engage. `swipe` is a flick — finger stays on screen at
release.

### `fling` (free-form) / `dircFling` (cardinal)

```sh
hdc shell uitest uiInput fling <from_x> <from_y> <to_x> <to_y> [velocity] [stepLen]
hdc shell uitest uiInput dircFling [direction] [velocity] [stepLen]
```

`direction` for `dircFling`: `0` left, `1` right, `2` up, `3` down.
Default 0. Velocity / step ranges as for swipe.

```sh
hdc shell uitest uiInput dircFling 2          # fling up at default 600 px/s
hdc shell uitest uiInput dircFling 3 1200     # downward, 1200 px/s
```

### `inputText` (coordinate-anchored) / `text` (focused field)

```sh
hdc shell uitest uiInput inputText <x> <y> <text>
hdc shell uitest uiInput text <text>          # API 18+; uses currently-focused field
```

Both clear existing text by default. For non-ASCII or strings >200
chars, the engine falls back to copy-paste internally; for short ASCII
it types char-by-char.

`text` is the better fit when you've already focused a field via a
preceding `click`. `inputText` is robust when there's no focused field
yet.

### `keyEvent` — physical keys + chords

```sh
hdc shell uitest uiInput keyEvent <keyID1> [keyID2] [keyID3]
```

`keyID1` accepts:
- The literal strings `Back`, `Home`, `Power` — these are **single-key
  only**, can't combine.
- Numeric `KeyCode` values (e.g. `2038` for `V`, `2072` for left
  Ctrl). Up to three keys for chords.

Quirks:
- Caps Lock (`KeyCode 2074`) does nothing. Use Shift + letter
  (`2047 2038` → uppercase `V`).
- Some platform-reserved chords (e.g. global screenshot) may be
  intercepted before the test app sees them.

Common keycodes worth memorising for quick scripts:

| Key | Code |
|---|---|
| Left Ctrl | 2072 |
| Left Shift | 2047 |
| Left Alt | 2045 |
| Enter | 2054 |
| Tab | 2049 |
| Space | 2050 |
| Backspace | 2055 |
| Esc | 2070 |
| Letters A–Z | 2017 (A) … 2042 (Z), contiguous |
| Digits 0–9 | 2000 (0) … 2009 (9) |

Full list:
`~/Dev/ohos/ohos-docs/en/application-dev/reference/apis-input-kit/js-apis-keycode.md`.

## `uiRecord record` / `uiRecord read`

Records gestures to `/data/local/tmp/record.csv` (despite the `.csv`
extension, content is one JSON object per line). Used for capturing a
manual session and replaying or analysing later.

| Flag | Arg | Default | Notes |
|---|---|---|---|
| `-W` | `<true\|false>` | `true` | Include matched component info per event. API 20+. |
| `-l` | — | off | After each event, also dump the layout JSON. API 20+. |
| `-c` | `<true\|false>` | `true` | Echo events to console. API 20+. |

```sh
hdc shell                                    # interactive — Ctrl+C is needed
uitest uiRecord record                       # default: log + match components
# … perform gestures on device …  Ctrl+C to stop
uitest uiRecord read                         # parse and print record.csv
exit
hdc file recv /data/local/tmp/record.csv ./record.csv
```

Each record line carries `EVENT_TYPE`, `OP_TYPE` (`click` /
`doubleClick` / `longClick` / `drag` / `pinch` / `swipe` / `fling`),
total `LENGTH`, `VELO`, gesture `duration`, and per-finger arrays with
`X_POSI` / `Y_POSI` / `X2_POSI` / `Y2_POSI` and the matched component
window IDs (`W1_*` / `W2_*`).

`uiRecord` cannot be used over `hdc shell <cmd>` because there's no
way to send SIGINT through that path.

## `start-daemon`

```sh
hdc shell uitest start-daemon
```

Starts the persistent UITest server. Required for ArkTS tests using
the Driver API; the test HAP launched via `aa test` will normally
spawn it on demand, so manual invocation is rare.

## `--version` / `help`

```sh
hdc shell uitest --version
hdc shell uitest help
hdc shell uitest uiInput help
```

## Capturing exit status

`hdc shell uitest …` will return 0 to the host even when the device
side reports an error (e.g. invalid coordinates, missing file). For
scripts, use the standard hdc workaround:

```sh
out=$(hdc shell "uitest uiInput click 100 100; echo __rc=\$?")
rc=${out##*__rc=}; rc=${rc%%[!0-9]*}
[ "$rc" = "0" ] || { printf '%s\n' "${out%__rc=*}" >&2; exit "$rc"; }
```

See the hdc skill for the full version of this idiom.
