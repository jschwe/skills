# ohos-rust — crates with C/C++ dependencies

The `CARGO_TARGET_*_LINKER` and `*_RUSTFLAGS` env vars in SKILL.md only
cover the **Rust** link step. They do **not** affect:

- `cc-rs` (`build.rs` of any `*-sys` crate that compiles C/C++).
- `bindgen` (header parsing for FFI bindings).
- `cmake` / `pkg-config` based builds vendored by other crates.

Each of these reads its own env vars. Get them wrong and the build
silently uses the *host* compiler against host headers, then either
fails at link time with relocation errors or — worse — links and
segfaults on the device.

## cc-rs / `*-sys` crates

`cc-rs` reads `<TOOL>_<TARGET>` (target with underscores, uppercased)
*first*, falling back to plain `<TOOL>`. Use the per-target form so
host builds in the same shell still work.

Point `CC_*` / `CXX_*` at the SDK's per-triple wrapper scripts — same
ones used as the Rust linker — so you don't need to repeat `--target=`
and `--sysroot=` in `CFLAGS_*` / `CXXFLAGS_*`. (Windows hosts: the
wrappers are POSIX shell scripts; use `clang.exe` + explicit flags as
shown in @ohos-rust/resources/windows-setup.md.)

```sh
NDK="$OHOS_SDK_NATIVE"
LLVM_BIN="$NDK/llvm/bin"

# aarch64-unknown-linux-ohos → AARCH64_UNKNOWN_LINUX_OHOS
T_AARCH64=AARCH64_UNKNOWN_LINUX_OHOS
export CC_${T_AARCH64}="$LLVM_BIN/aarch64-unknown-linux-ohos-clang"
export CXX_${T_AARCH64}="$LLVM_BIN/aarch64-unknown-linux-ohos-clang++"
export AR_${T_AARCH64}="$LLVM_BIN/llvm-ar"

# armv7
T_ARMV7=ARMV7_UNKNOWN_LINUX_OHOS
export CC_${T_ARMV7}="$LLVM_BIN/armv7-unknown-linux-ohos-clang"
export CXX_${T_ARMV7}="$LLVM_BIN/armv7-unknown-linux-ohos-clang++"
export AR_${T_ARMV7}="$LLVM_BIN/llvm-ar"

# x86_64
T_X86=X86_64_UNKNOWN_LINUX_OHOS
export CC_${T_X86}="$LLVM_BIN/x86_64-unknown-linux-ohos-clang"
export CXX_${T_X86}="$LLVM_BIN/x86_64-unknown-linux-ohos-clang++"
export AR_${T_X86}="$LLVM_BIN/llvm-ar"
```

Some `*-sys` crates also honor `RANLIB_<TARGET>`; if you hit
`ranlib: invalid argument` style errors, set
`RANLIB_<TARGET>="$LLVM_BIN/llvm-ranlib"` too.

If a particular crate insists on bypassing the wrappers (some hand-roll
their own clang invocation), fall back to the explicit form:

```sh
export CC_${T_AARCH64}="$LLVM_BIN/clang"
export CFLAGS_${T_AARCH64}="--target=aarch64-linux-ohos --sysroot=$NDK/sysroot"
# armv7 also needs: -march=armv7-a -mfloat-abi=softfp
```

## bindgen

`bindgen` invokes libclang to parse C headers. It does **not** pick up
`CFLAGS_*` automatically. Pass clang flags via
`BINDGEN_EXTRA_CLANG_ARGS_<TARGET>` (per-target, same naming convention
as cc-rs):

```sh
export BINDGEN_EXTRA_CLANG_ARGS_${T_AARCH64}="\
--target=aarch64-linux-ohos \
--sysroot=$NDK/sysroot \
-I$NDK/sysroot/usr/include/aarch64-linux-ohos"
```

The triple-specific include dir (`-I$NDK/sysroot/usr/include/<triple>`)
matters — without it, bindgen finds the multilib-shared headers but
misses the arch-specific ones (`bits/`, `asm/`, …) and dies on
`fatal error: 'bits/wordsize.h' file not found`.

`BINDGEN_EXTRA_CLANG_ARGS` (no target suffix) also works but applies to
every target the build sees, including the host build script — usually
not what you want.

## CMake-based crates

For crates using the `cmake` crate:

```sh
export CMAKE_TOOLCHAIN_FILE_${T_AARCH64}="$NDK/build/cmake/ohos.toolchain.cmake"
export OHOS_ARCH_${T_AARCH64}=aarch64
```

The OHOS NDK ships `ohos.toolchain.cmake` which already wires up the
right compiler, sysroot, and target — preferring it over hand-rolling
flags is much less brittle than the `cc-rs` route.

## Sanity check

After setting everything, `cargo build -vv --target <triple>` and look
for the C compile lines (search for `clang ` in the output). Confirm
you see `--target=<clang-triple>` and `--sysroot=...native/sysroot`
on every C compile invocation. If any line is missing those, that
dependency is being built for the host and will fail or misbehave at
link or runtime.
