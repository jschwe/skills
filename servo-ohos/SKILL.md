---
name: servo-ohos
description: Troubleshoot Servo on OpenHarmony / HarmonyOS — building the `.hap`, installing, launching, and debugging crashes specific to the OHOS port. Trigger when servoshell crashes on an OHOS device, or has other issues specific to the OHOS port.
---

# servo-ohos

A growing log of issues encountered when running Servo on OpenHarmony / HarmonyOS, plus the diagnostic recipes that surface their root cause. Adjacent to the [servoperf](../servoperf/SKILL.md) skill (host vs device measurement) and the user-level [ohos-rust](../../../../.claude/skills/ohos-rust/SKILL.md), [ohos-performance-testing](../../../../.claude/skills/ohos-performance-testing/SKILL.md), and [hdc](../../../../.claude/skills/hdc/SKILL.md) skills.

## How this skill is organized

Each known issue gets its own H2 section with a fixed shape:

1. **Symptom** — the user-visible failure (crash dialog, error code, log line).
2. **Confirm with logs** — the device-side commands that surface the *real* cause (the user-visible symptom usually buries it).
3. **Root cause** — the underlying mechanism.
4. **Fix** — concrete options, in order of cheapness.

Add new issues following that shape. Keep the diagnostic commands copy-pasteable — they're the highest-value part of the skill.

## Issue: napi binding fails to load — `Cannot read property X of undefined`

### Symptom

The `org.servo.servo` bundle launches, the scene is briefly foregrounded, then immediately terminates. JS faultlog under `/data/log/faultlog/faultlogger/jscrash-org.servo.servo-*.log` contains:

```
Reason:TypeError
Error name:TypeError
Error message:Cannot read property initServo of undefined
Stacktrace:
    at onCreate (servoshell|servoshell|<version>|src/main/ets/entryability/EntryAbility.ts:<line>:1)
```

This crash is generic — the *real* cause is buried in hilog before the JS frame runs. **Don't stop investigating at the JS frame.** The `servoshell` binding is `undefined` because OHOS's loader rejected `libservoshell.so` and the `import servoshell from 'libservoshell.so'` in [`support/openharmony/entry/src/main/ets/entryability/EntryAbility.ets`](../../../../servo/support/openharmony/entry/src/main/ets/entryability/EntryAbility.ets) silently resolved to `undefined`.

### Confirm with logs

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

### Root cause

OHOS NDK functions are versioned by **API level**. The bundle's `apiCompatibleVersion` (in `AppScope/app.json5`, copied into the installed `bm dump`) declares the minimum API level the bundle expects from the device. The device's libraries — `libavplayer.so`, `libace_napi.z.so`, etc. — only export symbols introduced at or below the device's actual API level.

Mismatch causes the loader to keep going past `dlopen`, only to fail at the per-symbol relocation step. The error appears at the very first call into the napi entry, which is why the JS-side error looks generic.

Pin the version pieces with these commands:

```bash
# Build SDK (the version that produced the .so):
cat /Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native/oh-uni-package.json
# → "apiVersion": "22", "version": "6.0.2.130"

# Device's compatible/target API level (what the runtime can satisfy):
hdc shell "bm dump -n org.servo.servo | grep -E 'apiCompatibleVersion|apiTargetVersion|versionName'"
# apiCompatibleVersion: 60000020   ← device runtime caps out at API 20
# apiTargetVersion:     60000020

# Confirm the device's actual NDK lib doesn't export the missing symbol:
hdc file recv /system/lib64/libavplayer.so /tmp/dev-libavplayer.so
strings /tmp/dev-libavplayer.so | grep '^OH_AVPlayer'    # what the device actually has
strings ~/Library/OpenHarmony/Sdk/<api>/native/sysroot/usr/lib/aarch64-linux-ohos/libavplayer.so | grep '^OH_AVPlayer'  # what each SDK API level offers
```

In our case the build SDK was API 22 (which exports `OH_AVPlayer_SetDataSource`), the device caps at API 20 (which only has `OH_AVPlayer_SetURLSource` / `SetFDSource`), and [`components/media/backends/ohos/Cargo.toml`](../../../../servo/components/media/backends/ohos/Cargo.toml) pinned `ohos-media-sys = { features = ["api-21"] }` — so `libservoshell.so` ended up linking against the newer symbol.

### Fix

In order of cheapness:

1. **Re-point the build at the device's API level.** Override `OHOS_SDK_NATIVE` to a matching SDK before running `mach build --ohos`:

   ```bash
   export OHOS_SDK_NATIVE=$OHOS_BASE_SDK_HOME/<api-level>/native
   ./mach build --ohos --flavor=harmonyos --profile=release \
                --features tracing,tracing-hitrace
   ```

   This works as long as no Servo Rust code references symbols newer than the device's API level — i.e. no `ohos-media-sys` or similar `features = ["api-NN"]` exceeds the target. If the build still fails at link time, fall through to (2).

2. **Lower the `ohos-media-sys` (or other `ohos-*-sys`) feature pin** in [`components/media/backends/ohos/Cargo.toml`](../../../../servo/components/media/backends/ohos/Cargo.toml) — e.g. `features = ["api-20"]` — and patch the call site to use a symbol that exists at that level (`OH_AVPlayer_SetURLSource` or `OH_AVPlayer_SetFDSource` instead of `SetDataSource` in [`components/media/backends/ohos/ohos_media/source.rs`](../../../../servo/components/media/backends/ohos/ohos_media/source.rs)). Likely needs minor signature changes — the source kinds aren't drop-in equivalents.

3. **Update the device's HarmonyOS / OpenHarmony build** so its `apiCompatibleVersion` covers what the SDK uses. Out of band of any host-side fix; only realistic if the user controls the device firmware.

4. **Drop the OHOS media backend** from the build (if a feature flag exists). Last resort — measurements that need media playback can't run.

### Why the JS error is misleading

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
