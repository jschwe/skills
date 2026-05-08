---
name: ohos-uitest
description: Drive UI automation on OpenHarmony / OHOS / HarmonyOS devices using the on-device `uitest` tool — taps, swipes, screenshots, layout dumps, screen recording — invoked via `hdc shell uitest …`, or via the ArkTS `@kit.TestKit` Driver API for proper test suites. Trigger when the user asks to automate UI on an OHOS device, mentions `uitest`, wants screenshots / layout dumps / event injection from the host, or writes ArkTS UI tests using `Driver`, `Component`, or `ON` from `@kit.TestKit`.
---

# ohos-uitest

OHOS ships a `uitest` binary at `/system/bin/uitest` that exposes UI
automation over `hdc shell`. The same engine also backs the ArkTS
`@kit.TestKit` API (`Driver`, `Component`, `ON`) used in JsUnit /
hypium test suites.

Two modes, picked by what you need:

| Need | Use | Strength |
|---|---|---|
| Scripted host-side automation, screenshots, layout dumps, simple input injection | `hdc shell uitest …` (CLI) | Zero on-device setup. Coordinate-based — brittle when UIs change. |
| Find components by text/type/id, assert UI state, run tests in CI | ArkTS `Driver` from `@kit.TestKit` | Robust matchers, assertions, page-load waits. Requires a test HAP. |

This skill assumes the **hdc** skill is already in scope for the wire
layer. In particular `hdc shell` swallows device-side exit codes —
relevant for any script that runs `uitest` and checks success. See the
hdc skill's "Critical gotcha" section before scripting.

## CLI — quickest path

All commands run as `hdc shell uitest <cmd> …` from the host. Quote
the whole command if any argument contains spaces or shell
metacharacters (the OHOS docs are explicit about this — input is
re-parsed by `/bin/sh` on device).

```sh
# Screenshot — saved as /data/local/tmp/<timestamp>.png by default.
hdc shell uitest screenCap
hdc shell uitest screenCap -p /data/local/tmp/now.png
hdc file recv /data/local/tmp/now.png ./now.png

# Layout dump — JSON tree of the visible UI.
hdc shell uitest dumpLayout -p /data/local/tmp/layout.json
hdc shell uitest dumpLayout -b com.example.app           # filter by bundle
hdc shell uitest dumpLayout -a -p /data/local/tmp/full.json   # include extra attrs

# Inject a tap, swipe, or text input.
hdc shell uitest uiInput click 540 1200
hdc shell uitest uiInput swipe 100 1500 100 500 800
hdc shell uitest uiInput inputText 540 800 "hello world"

# Send keys (Back / Home / Power, or KeyCode numbers).
hdc shell uitest uiInput keyEvent Home
hdc shell uitest uiInput keyEvent Back
hdc shell uitest uiInput keyEvent 2072 2038        # Ctrl+V (paste)

# Record a UI session. Ctrl+C to stop. Output: /data/local/tmp/record.csv (JSONL).
hdc shell                          # interactive shell — recording needs SIGINT
uitest uiRecord record
# … perform gestures …  Ctrl+C
uitest uiRecord read               # parse and print
```

For full parameter listings (modifier flags on `screenCap`,
`dumpLayout`, `uiInput dircFling`, `uiRecord`, key-code handling), see
@ohos-uitest/resources/cli.md.

## ArkTS Driver API — robust tests

For test suites where coordinates are too fragile, use the ArkTS API.
The skeleton:

```typescript
import { describe, it, expect, Level } from '@ohos/hypium';
import { abilityDelegatorRegistry, Driver, ON } from '@kit.TestKit';

const delegator = abilityDelegatorRegistry.getAbilityDelegator();

export default function abilityTest() {
  describe('myFeatureTest', () => {
    it('opens settings and toggles wifi', Level.LEVEL3, async (done: Function) => {
      const driver = Driver.create();
      await delegator.startAbility({
        bundleName: 'com.example.settings',
        abilityName: 'EntryAbility',
      });
      await driver.waitForIdle(4000, 5000);

      const wifi = await driver.findComponent(ON.text('Wi-Fi'));
      await wifi.click();

      await driver.assertComponentExist(ON.text('Available networks'));
      done();
    });
  });
}
```

Key APIs (from `@kit.TestKit`):

- `Driver.create()` — entry point. One per test, no concurrent calls.
- `ON.text(s)` / `ON.type('Button')` / `ON.id('foo')` / `ON.within(parent)` — matcher builders. Compose with `.within()` for nested searches.
- `driver.findComponent(on)` / `driver.findComponents(on)` — return one / all matches.
- `driver.waitForComponent(on, timeoutMs)` — block until appears.
- `driver.waitForIdle(idleMs, totalTimeoutMs)` — wait until UI stabilises.
- `driver.click/swipe/drag/fling/inputText` — coordinate-level events.
- `driver.triggerKey(KeyCode.X)` / `driver.triggerCombineKeys(a, b, …)`.
- `driver.screenCap(path, displayId?)` — must save to **app sandbox** (`/data/storage/el2/base/cache/`), not `/data/local/tmp/`.
- `driver.assertComponentExist(on)` — built-in assertion.

For test-runner setup, sandbox paths, mouse/stylus/crown/touchpad
APIs, event observers, common error codes (e.g. `17000005` "device not
supported" for window ops), and patterns for handling the "component
disappeared between find and act" race, see
@ohos-uitest/resources/arkts-api.md.

## Constraints worth knowing up front

- **`uitest start-daemon` and the test HAP.** The full UITest engine
  is reachable only from a test HAP launched via `aa test`, with APL
  `normal`. CLI subcommands (`screenCap`, `dumpLayout`, `uiInput`,
  `uiRecord`) work without a test HAP — they cover most ad-hoc
  automation.
- **One UITest at a time.** Concurrent UITest calls fail with
  "uitest-api does not allow calling concurrently". Don't run multiple
  tests in parallel processes against the same device.
- **`uiRecord record` needs Ctrl+C.** Run it from interactive
  `hdc shell`, not `hdc shell <cmd>` — the latter has no signal
  channel.
- **Coordinate-based input is fragile.** Layouts shift between
  devices, orientations, and OS versions. Use `dumpLayout` once to find
  components, then prefer the ArkTS `ON.text/type/id` matchers when
  building anything that has to keep working.
- **Caps Lock (KeyCode 2074) is a no-op.** For uppercase input via
  `keyEvent`, use Shift + letter (`2047 2038` for `V`).
- **Multi-display flags are API 20+.** `screenCap -d <id>` and
  `dumpLayout -d <id>` need a recent device. Query displays with
  `hidumper`.

## OHOS docs

Authoritative source for this skill:

- `~/Dev/ohos/ohos-docs/en/application-dev/application-test/uitest-guidelines.md` — main user guide (CLI + ArkTS).
- `~/Dev/ohos/ohos-docs/en/application-dev/reference/apis-test-kit/js-apis-uitest.md` — full ArkTS API reference.
- `~/Dev/ohos/ohos-docs/en/application-dev/reference/apis-input-kit/js-apis-keycode.md` — KeyCode enum used by `keyEvent` / `triggerKey`.
