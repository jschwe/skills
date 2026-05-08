# OHOS bundle crashes at launch: `Cannot read property initServo of undefined`

## Symptom

The `org.servo.servo` bundle launches, the scene is briefly foregrounded, then immediately terminates. JS faultlog under `/data/log/faultlog/faultlogger/jscrash-org.servo.servo-*.log` contains:

```
Reason:TypeError
Error name:TypeError
Error message:Cannot read property initServo of undefined
Stacktrace:
    at onCreate (servoshell|servoshell|<version>|src/main/ets/entryability/EntryAbility.ts:<line>:1)
```

This crash is generic — the *real* cause is buried in hilog before the JS frame runs. **Don't stop investigating at the JS frame.** The `servoshell` binding is `undefined` because OHOS's loader rejected `libservoshell.so` and the `import servoshell from 'libservoshell.so'` in `support/openharmony/entry/src/main/ets/entryability/EntryAbility.ets` silently resolved to `undefined`.

## Confirm

Run the launch with hilog cleared first, then dump everything from the app's PID:

```bash
hdc shell "hilog -r"                                    # clear ring buffer
hdc shell "aa force-stop -b org.servo.servo"
hdc shell "aa start -a EntryAbility -b org.servo.servo -U https://example.com/"
sleep 4
hdc shell "hilog -x" > /tmp/hilog.txt                   # full dump
grep -E '<servo-pid>' /tmp/hilog.txt | grep -iE 'load|dlopen|napi|reloc|symbol|MUSL-LDSO'
```

(Pid: grab from `bm dump` post-spawn or from any `org.servo.servo/<TAG>` line in the dump.)

The smoking gun lives under tag `MUSL-LDSO` and `org.servo.servo/NAPI`:

```
W C03F00/MUSL-LDSO: relocating failed: symbol not found.
  dso=/data/storage/el1/bundle/libs/arm64/libservoshell.so
  s=OH_AVPlayer_SetDataSource use_vna_hash=0 van_hash=0
W C03F01/org.servo.servo/NAPI: First attempt: load app module failed.
  Error relocating /data/storage/el1/bundle/libs/arm64/libservoshell.so:
  OH_AVPlayer_SetDataSource: symbol not found
```

`MUSL-LDSO` is OHOS's musl-libc dynamic loader. `relocating failed: symbol not found` means a function that `libservoshell.so` was linked against does not exist in any of the device's `DT_NEEDED` shared libraries at runtime — almost always because the build SDK is at a higher API level than the device runtime supports.

## Root cause

OHOS NDK functions are versioned by **API level**. The device's libraries — `libavplayer.so`, `libace_napi.z.so`, etc. — only export symbols introduced at or below the **device's** actual API level (set by the firmware build, not by the bundle).

Mismatch causes the loader to keep going past `dlopen`, only to fail at the per-symbol relocation step. The error appears at the very first call into the napi entry, which is why the JS-side error looks generic.

Three different "API version" numbers are involved; do not conflate them:

| Source | What it tells you | How to read it |
|---|---|---|
| **Build SDK** | The API level the `.so` was *compiled* against — i.e. the highest level whose symbols `libservoshell.so` may have linked. | `cat /Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native/oh-uni-package.json` (or the equivalent on Linux/Windows) |
| **Device firmware** | The API level the *device runtime* actually exposes — i.e. the highest level whose symbols are present in `/system/lib64/lib*.so`. **This is the value that determines whether relocation succeeds.** | `hdc shell "param get const.ohos.apiversion"` (also useful: `const.ohos.fullname`, `const.ohos.releasetype`, `const.ohos.version.security_patch`) |
| **Bundle manifest** | What the bundle *declares* it needs from the device (`apiCompatibleVersion`) and what it was built for (`apiTargetVersion`). These come from `AppScope/app.json5` and gate install-time compatibility checks; they do not determine what symbols are available at runtime. | `hdc shell "bm dump -n org.servo.servo \| grep -E 'apiCompatibleVersion\|apiTargetVersion\|versionName'"` |

For diagnosing this crash, pin the **build SDK** against the **device firmware**:

```bash
# Build SDK (the version that produced the .so):
cat /Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native/oh-uni-package.json
# → "apiVersion": "22", "version": "6.0.2.130"

# Device's actual firmware API level (what symbols exist at runtime):
hdc shell "param get const.ohos.apiversion"
# → 20

# (Optional) bundle-declared compatibility — useful to verify the install rules,
# but does NOT tell you whether runtime relocation will succeed:
hdc shell "bm dump -n org.servo.servo | grep -E 'apiCompatibleVersion|apiTargetVersion|versionName'"

# Confirm the device's actual NDK lib doesn't export the missing symbol:
hdc file recv /system/lib64/libavplayer.so /tmp/dev-libavplayer.so
strings /tmp/dev-libavplayer.so | grep '^OH_AVPlayer'    # what the device actually has
strings ~/Library/OpenHarmony/Sdk/<api>/native/sysroot/usr/lib/aarch64-linux-ohos/libavplayer.so | grep '^OH_AVPlayer'  # what each SDK API level offers
```

In a representative case the build SDK was API 22 (which exports `OH_AVPlayer_SetDataSource`), the device's `const.ohos.apiversion` reported API 20 (which only has `OH_AVPlayer_SetURLSource` / `SetFDSource`), and `components/media/backends/ohos/Cargo.toml` pinned `ohos-media-sys = { features = ["api-21"] }` — so `libservoshell.so` ended up linking against the newer symbol.

## Fix / work-around

1. **Re-point the build at the device's API level.** Override `OHOS_SDK_NATIVE` to a matching SDK before running `mach build --ohos`:

   ```bash
   export OHOS_SDK_NATIVE=$OHOS_BASE_SDK_HOME/<api-level>/native
   ./mach build --ohos --flavor=harmonyos
   ```

   This works as long as no Servo Rust code references symbols newer than the device's API level — i.e. no `ohos-media-sys` or similar `features = ["api-NN"]` exceeds the target. If the build still fails at link time, fall through to (2).

## Why the JS error is misleading

The chain is:

```
EntryAbility.ets:  import servoshell from 'libservoshell.so'
                    ↓ (OHOS's napi module loader)
ark_native_engine: RequireNapi("default/servoshell")
                    ↓
LoadModuleLibrary: dlopen("libservoshell.so")
                    ↓
MUSL-LDSO:         relocating failed: symbol not found  ← real cause
                    ↑
LoadModuleLibrary: returns NULL, RequireNapi propagates "load failed"
                    ↑
napi engine:       binds `servoshell` to undefined (no exception thrown)
                    ↑
EntryAbility:      next line is `servoshell.initServo(opts)` → TypeError on `.initServo`
```

The napi loader logs the dlopen failure as a `W` (warning), not an `E`, so it doesn't trip OHOS's automatic crash collection. Only the downstream JS TypeError gets a faultlog. Always grep `MUSL-LDSO` and `org.servo.servo/NAPI` in hilog when the JS error shape is "Cannot read property … of undefined" right after the bundle launches.
