# ohos-uitest — ArkTS Driver API

Long-form companion to SKILL.md. Patterns for writing UI tests in
ArkTS using `@kit.TestKit` (which re-exports the same `Driver`,
`Component`, `ON` types as `@ohos.UiTest`).

## Test-runner setup

UITest tests run inside a **test HAP** launched by `aa test`. The
hypium framework wraps the standard JsUnit lifecycle. Skeleton:

```typescript
import { describe, it, expect, Level } from '@ohos/hypium';
import { abilityDelegatorRegistry, Driver, ON, Component } from '@kit.TestKit';
import { UIAbility, Want } from '@kit.AbilityKit';

const delegator = abilityDelegatorRegistry.getAbilityDelegator();

export default function abilityTest() {
  describe('myFeature', () => {
    it('case_1', Level.LEVEL3, async (done: Function) => {
      const driver = Driver.create();   // one Driver per test
      const want: Want = {
        bundleName: abilityDelegatorRegistry.getArguments().bundleName,
        abilityName: 'EntryAbility',
      };
      await delegator.startAbility(want);
      await driver.waitForIdle(4000, 5000);

      // …assertions / actions…

      done();
    });
  });
}
```

The test HAP must declare the test ability in `module.json5` and run at
APL `normal` (the default for app-developed test HAPs). Run from the
host with:

```sh
hdc shell aa test -b com.example.app -m entry_test \
                  -s unittest /ets/testrunner/OpenHarmonyTestRunner \
                  -s class myFeature
```

## Matchers — `ON.…`

`ON` builds a query. None of these methods perform the search;
they return an `On` value you pass to `findComponent` /
`findComponents` / `assertComponentExist` / `waitForComponent`.

| Method | Matches | Example |
|---|---|---|
| `ON.text(s, MatchPattern?)` | text content | `ON.text('Save')`, `ON.text('Item', MatchPattern.CONTAINS)` |
| `ON.id(s)` | the `id` attr set on the component | `ON.id('saveBtn')` |
| `ON.type(s)` | component type as it appears in `dumpLayout` | `ON.type('Button')` |
| `ON.description(s)` | accessibility label | `ON.description('Volume')` |
| `ON.clickable(b)` / `ON.scrollable(b)` / `ON.enabled(b)` / `ON.focused(b)` / `ON.selected(b)` / `ON.checkable(b)` / `ON.checked(b)` / `ON.longClickable(b)` | state-based filters | `ON.clickable(true)` |
| `ON.within(parent)` | nest inside another `On` query | `ON.text('123').within(ON.type('Scroll'))` |
| `ON.isAfter(other)` / `ON.isBefore(other)` | sibling-order constraint | `ON.type('Text').isAfter(ON.id('header'))` |

Combine multiple constraints by chaining: `ON.type('Button').text('OK')`
finds a Button whose text is "OK".

`MatchPattern`: `EQUALS` (default), `CONTAINS`, `STARTS_WITH`,
`ENDS_WITH`. Useful for IDs that include random suffixes.

## Driver — common operations

Every method below is `async`; `await` everything (uitest fails with
"uitest-api does not allow calling concurrently" if you don't).

### Find / wait

```ts
const c: Component = await driver.findComponent(ON.text('Next'));
const cs: Component[] = await driver.findComponents(ON.type('ListItem'));
const c2 = await driver.waitForComponent(ON.id('toast'), 2000);   // ms
await driver.waitForIdle(idleMs, totalTimeoutMs);                 // page settles
await driver.delayMs(500);                                        // unconditional sleep
```

### Coordinate-level input

```ts
await driver.click(x, y);
await driver.doubleClick(x, y);
await driver.longClick(x, y);
await driver.swipe(fromX, fromY, toX, toY, speed);
await driver.drag(fromX, fromY, toX, toY, speed);
await driver.fling({ x, y }, { x, y }, stepLen, speed);
await driver.fling(UiDirection.DOWN, speed);
await driver.inputText({ x, y }, 'hello');
```

API-20+ multi-display variants take `Point3`-style objects:

```ts
await driver.clickAt({ x: 100, y: 200, displayId: 0 });
await driver.swipeBetween({ x, y, displayId }, { x, y, displayId }, speed);
await driver.dragBetween({ x, y, displayId }, { x, y, displayId }, speed, longPressMs);
```

### Component-level actions

```ts
await c.click();
await c.doubleClick();
await c.longClick();
await c.inputText('abc');
await c.inputText('abc', { paste: true, addition: true });   // API 20+: append, paste mode
await c.scrollSearch(ON.text('foo'));                        // scroll until found
await c.pinchOut(scale); await c.pinchIn(scale);
await c.dragTo(otherComponent);
const center = await c.getBoundsCenter();    // useful for hybrid coord/component flows
const text = await c.getText();
const id = await c.getId();
const bounds = await c.getBounds();
```

### Keyboard

```ts
import { KeyCode } from '@kit.InputKit';

await driver.triggerKey(KeyCode.KEYCODE_BACK);
await driver.triggerCombineKeys(KeyCode.KEYCODE_CTRL_LEFT, KeyCode.KEYCODE_S);
```

### Mouse / stylus / crown / touchpad

API-20+ unless noted. These all throw error code `17000005` ("device
not supported") on form factors that lack the matching hardware —
phone vs PC vs watch vs 2-in-1. Wrap in try/catch when targeting
multiple device types.

```ts
await driver.mouseClick({ x, y }, MouseButton.MOUSE_BUTTON_LEFT);
await driver.mouseMoveTo({ x, y });
await driver.mouseDrag({ x, y }, { x, y }, speed);
await driver.mouseScroll({ x, y }, deltaUp /* bool */, ticks, KeyCode.KEYCODE_CTRL_LEFT?);
await driver.mouseLongClick({ x, y }, MouseButton.MOUSE_BUTTON_LEFT);

await driver.penClick({ x, y });
await driver.penDoubleClick({ x, y });
await driver.penLongClick({ x, y }, pressure);
await driver.penSwipe({ x, y }, { x, y }, speed, pressure);

await driver.touchPadMultiFingerSwipe(fingerCount, UiDirection.UP);
await driver.crownRotate(ticks, speed);     // smartwatch only
```

### Multi-pointer (custom gestures)

```ts
import { PointerMatrix } from '@kit.TestKit';
const p = PointerMatrix.create(/*fingers=*/2, /*steps=*/2);
p.setPoint(0, 0, { x: 100, y: 100 });   // finger 0, step 0
p.setPoint(0, 1, { x: 200, y: 100 });
p.setPoint(1, 0, { x: 100, y: 200 });
p.setPoint(1, 1, { x: 200, y: 200 });
await driver.injectMultiPointerAction(p);
```

### Display

```ts
const size = await driver.getDisplaySize();      // Point { x: width, y: height }
const dens = await driver.getDisplayDensity();
await driver.wakeUpDisplay();
await driver.setDisplayRotation(DisplayRotation.ROTATION_90);
```

### Window

```ts
const w = await driver.findWindow({ active: true });   // or { bundleName, focused }
await w.minimize();
await w.maximize();
await w.resume();
await w.split();
await w.close();
await w.moveTo(x, y);
await w.resize(width, height, ResizeDirection.LEFT);   // form-factor dependent — may throw 17000005
```

### Assertions

```ts
await driver.assertComponentExist(ON.text('Logged in'));
// negation: just findComponent in try/catch, or check returned component for null
```

### Screenshot (sandbox path required!)

```ts
const path = '/data/storage/el2/base/cache/cap.png';   // app sandbox
await driver.screenCapture(path, { left, top, right, bottom });
await driver.screenCap(path, displayId);    // API 20+ — full screen, specific display
```

`/data/local/tmp/` paths from the CLI section will throw a
permissions error here — the test HAP's APL is `normal`.

### Event observers

For toasts / dialogs that appear and disappear too fast for
`waitForComponent`:

```ts
const obs = driver.createUIEventObserver();
obs.once('toastShow', (info: UIElementInfo) => {
  // info: bundleName, type, text
});
// or 'dialogShow'
```

The callback fires on the next matching event after registration.

## Common pitfalls

### "Component does not exist on current UI"

```
does not exist on current UI! Check if the UI has changed after you got the widget object
```

The component you found has been recycled / re-rendered between
`findComponent` and the action. Find-then-act needs to be tight, or
re-find inside the action call:

```ts
// Bad:
const c = await driver.findComponent(ON.text('Save'));
await driver.waitForIdle(2000, 5000);   // UI may shift here
await c.click();                        // <-- may throw

// Better:
await driver.waitForIdle(2000, 5000);
await (await driver.findComponent(ON.text('Save'))).click();
```

For lists that reflow during scroll, use `scrollSearch` rather than
caching a `Component`.

### "Cannot connect to AAMS, RET_ERR_CONNECTION_EXIST"

Another tool that depends on UITest is running (e.g. an old uitest
daemon, the AccessibilityManager-attached recorder). Stop the
conflicting tool or reboot the device.

### "uitest-api does not allow calling concurrently"

Two causes:
- A missing `await` on a UITest call earlier in the test.
- The test runner started multiple processes that all use UITest.

Audit `await`s; ensure tests run in a single hypium process.

### Tests pass locally, fail in CI on a different device

Coordinate-based input (`driver.click(540, 1200)`) is the usual
culprit — different DPIs / aspect ratios put components elsewhere. Use
component-based input (`(await driver.findComponent(...)).click()`)
wherever possible. For coordinate-only paths, derive coords from
`getDisplaySize()` / `getBoundsCenter()` instead of hard-coding.

## API reference

Full ArkTS API surface (every overload, every parameter):
`~/Dev/ohos/ohos-docs/en/application-dev/reference/apis-test-kit/js-apis-uitest.md`.

KeyCode enum:
`~/Dev/ohos/ohos-docs/en/application-dev/reference/apis-input-kit/js-apis-keycode.md`.
