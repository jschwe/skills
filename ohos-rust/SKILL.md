---
name: ohos-rust
description: Set up cross-compilation of Rust binaries for OpenHarmony / OHOS / HarmonyOS using the standalone command-line SDK. Trigger when the user wants to build a Rust crate for an OHOS device, mentions targets like aarch64-unknown-linux-ohos / armv7-unknown-linux-ohos / x86_64-unknown-linux-ohos, hits linker errors building for OHOS, or asks how to push a Rust binary to a HarmonyOS device.
---

# ohos-rust

Cross-compile Rust standalone binaries for OpenHarmony devices using the
standalone command-line SDK and stable rustup targets.

The skill assumes:
- Output is a **standalone binary** (no NAPI / cdylib loaded by an ArkTS app).
- Rust is installed via **rustup**, stable channel — the `*-unknown-linux-ohos`
  targets ship prebuilt.
- The target device has root access via `hdc shell` or signing is not required 
  for running binaries.

## Locate the SDK before doing anything else

Resolve `$OHOS_SDK_NATIVE` once, in this order — stop at the first hit.
`OHOS_SDK_NATIVE` is the authoritative variable for this skill; it points
at the `native/` directory of the SDK. Env vars in steps 1–2 already
point at `native/`; the ones in step 3 point at an SDK root that
contains `native/` (possibly nested under an api-level directory).

1. `$OHOS_SDK_NATIVE` set → use it directly.
2. `$OHOS_NDK_HOME` set → use it directly.
3. SDK-root env vars, first hit wins:
   - `$OHOS_SDK_HOME`
   - `$OHOS_BASE_SDK_HOME`
   - `$DEVECO_SDK_HOME` (DevEco Studio layout — typically
     `<root>/default/openharmony/<api>/native/`; resolve through the
     intermediate dirs as needed)

   For each: if `<root>/native` exists, use it; otherwise pick the
   highest-numbered `<api>/native` (recursively, for the DevEco case).
4. Bundled with a DevEco Studio installation: 
   `<DevEcoStudioInstallationDir>/sdk/default/openharmony/native`
5. Nothing matched → **ask the user** for the SDK root and offer to record
   as a memory.

Verify by checking that `$OHOS_SDK_NATIVE/llvm/bin/clang` and
`$OHOS_SDK_NATIVE/sysroot` both exist. If the SDK is api-level-versioned
(`<sdk>/<api>/native/`), pick the highest numeric `<api>` directory.

### Picking the API level when a device is connected

If multiple API levels are installed under the SDK root **and** a target
device is reachable via `hdc`, prefer the SDK whose API level matches
the device. Query the device with:

```sh
hdc shell 'param get const.ohos.apiversion'
# → 12     (or 11, 14, …)
```

Then point `$OHOS_SDK_NATIVE` at the matching `<api>/native/` directory.
Building against a newer SDK than the device runs is the usual cause of
`undefined reference` / missing-symbol errors at load time on the
device — the binary references libc / OHOS APIs that don't exist in the
device's older runtime.

If `hdc list targets` is empty, see the sandbox-visibility note in
@ohos-rust/resources/run-on-device.md before falling back to "highest
installed API level".

## Add the required rustup targets

```sh
# Pick the ones you need for the project.
rustup target add aarch64-unknown-linux-ohos \
                  armv7-unknown-linux-ohos \
                  x86_64-unknown-linux-ohos
```

Stable channel only — no nightly needed. If `rustup target add` reports the
target as unknown, the local rustup is too old; `rustup self update && rustup update stable` first.

## Wire up the linker

The OHOS SDK ships per-target clang wrapper scripts in
`$OHOS_SDK_NATIVE/llvm/bin/`, named after the **Rust** triple:

```
aarch64-unknown-linux-ohos-clang
armv7-unknown-linux-ohos-clang
x86_64-unknown-linux-ohos-clang
```

Each wrapper is a small shell script that invokes `clang` with the right
`--target=`, `--sysroot=`, and (for armv7) `-march=`/`-mfloat-abi=` baked
in. Pointing cargo at the wrapper means you don't have to spell any of
that out, and you don't have to remember that `armv7-unknown-linux-ohos`
maps to clang target `arm-linux-ohos`.

```sh
NDK="$OHOS_SDK_NATIVE"

export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_OHOS_LINKER="$NDK/llvm/bin/aarch64-unknown-linux-ohos-clang"
export CARGO_TARGET_ARMV7_UNKNOWN_LINUX_OHOS_LINKER="$NDK/llvm/bin/armv7-unknown-linux-ohos-clang"
export CARGO_TARGET_X86_64_UNKNOWN_LINUX_OHOS_LINKER="$NDK/llvm/bin/x86_64-unknown-linux-ohos-clang"
```

Then build:

```sh
cargo build --release --target aarch64-unknown-linux-ohos
```

The skill deliberately uses **env vars only** rather than touching
`~/.cargo/config.toml`, so nothing about a particular project's setup
leaks into the user's global cargo config.

**Windows hosts:** the wrappers above are POSIX shell scripts and won't
execute under cmd.exe / PowerShell. On Windows, set up the linker via
plain env vars (PowerShell-syntax) plus rustflags carrying `--target=`
and `--sysroot=` directly — see @ohos-rust/resources/windows-setup.md.

**Bypassing the wrappers** (advanced, e.g. when overriding the sysroot)
requires the Rust→clang triple mapping the wrappers normally hide:

| Rust triple                    | clang `--target=`     |
|--------------------------------|-----------------------|
| `aarch64-unknown-linux-ohos`   | `aarch64-linux-ohos`  |
| `armv7-unknown-linux-ohos`     | `arm-linux-ohos` (+ `-march=armv7-a -mfloat-abi=softfp`) |
| `x86_64-unknown-linux-ohos`    | `x86_64-linux-ohos`   |

For the long-form walkthrough — including SDK layout, picking the right
sysroot when there are multiple, common linker errors and their fixes 
— see @ohos-rust/resources/setup.md.

## Pushing and running on a device

OHOS Rust binaries dynamically link `libc++_shared.so`; that library is
**not** on the device by default. Push it alongside the binary and set
`LD_LIBRARY_PATH`. Full hdc recipe (incl. `/data/local/tmp` permissions
and capturing the device-side exit code, since `hdc shell` swallows it):
@ohos-rust/resources/run-on-device.md.

The hdc skill covers the device-connector itself — particularly the
silent-exit-code gotcha that bites any "build → push → run → check $?"
script.

## Crates with C dependencies (cc-rs, bindgen, *-sys)

When a dependency builds C/C++ via `cc-rs` or generates bindings via
`bindgen`, the Rust linker env vars above are not enough — those crates
read `CC_<triple>`, `CXX_<triple>`, `AR_<triple>`, and
`BINDGEN_EXTRA_CLANG_ARGS_<triple>` directly. Setup and a worked example:
@ohos-rust/resources/c-deps.md.

## OHOS docs

Authoritative OHOS docs are available at `gitcode.com/openharmony/docs`.
