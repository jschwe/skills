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

`cc-rs` looks up tool variables in this order ([cc-rs source][cc-target-envs]):

1. `<TOOL>_<TARGET>` — target as-is, with hyphens (`CC_aarch64-unknown-linux-ohos`)
2. `<TOOL>_<TARGET_U>` — target lowercase with hyphens replaced by underscores (`CC_aarch64_unknown_linux_ohos`)
3. `TARGET_<TOOL>` — applies to whichever cross-target is active (`TARGET_CC`)
4. `<TOOL>` — plain `CC`

[cc-target-envs]: https://github.com/rust-lang/cc-rs/blob/main/src/lib.rs

**The triple is lowercase.** `CC_AARCH64_UNKNOWN_LINUX_OHOS` (uppercase)
is *not* a form cc-rs recognizes — setting only that variant silently
falls through to plain `cc`, which on a non-OHOS host produces "C
compiler cannot create executables" from configure-style build scripts.

Prefer the `TARGET_<TOOL>` form — it's shorter, doesn't carry the case-typo
risk and is also recognized by autoconf based configure scripts.
In some cases build.rs scripts might set a higher-priority variable than `TARGET_<TOOL>`;
if that causes issues, try setting `<TOOL>_<TARGET>` explicitly.

Point the compiler vars at the SDK's per-triple wrapper scripts — same
ones used as the Rust linker — so you don't need to repeat `--target=`
and `--sysroot=` in `CFLAGS_*` / `CXXFLAGS_*`. (Windows hosts: the
wrappers are POSIX shell scripts; use `clang.exe` + explicit flags as
shown in @ohos-rust/resources/windows-setup.md.)

```sh
NDK="$OHOS_SDK_NATIVE"
LLVM_BIN="$NDK/llvm/bin"

# TARGET_* form.
export TARGET_CC="$LLVM_BIN/aarch64-unknown-linux-ohos-clang"
export TARGET_CXX="$LLVM_BIN/aarch64-unknown-linux-ohos-clang++"
export TARGET_AR="$LLVM_BIN/llvm-ar"

# Or, per-target form — lowercase triple, hyphens → underscores.
export CC_aarch64_unknown_linux_ohos="$LLVM_BIN/aarch64-unknown-linux-ohos-clang"
export CXX_aarch64_unknown_linux_ohos="$LLVM_BIN/aarch64-unknown-linux-ohos-clang++"
export AR_aarch64_unknown_linux_ohos="$LLVM_BIN/llvm-ar"

# Same pattern for armv7 / x86_64:
#   CC_armv7_unknown_linux_ohos, CC_x86_64_unknown_linux_ohos, etc.
```

Some `*-sys` crates also honor `TARGET_RANLIB>`; if you hit
`ranlib: invalid argument` style errors, set `TARGET_RANLIB`="$LLVM_BIN/llvm-ranlib"
or `RANLIB_<target>`.

If a particular crate insists on bypassing the wrappers (some hand-roll
their own clang invocation), fall back to the explicit form:

```sh
export TARGET_CC="$LLVM_BIN/clang"
export TARGET_CFLAGS="--target=aarch64-linux-ohos --sysroot=$NDK/sysroot"
# armv7 also needs: -march=armv7-a -mfloat-abi=softfp
```

## bindgen

`bindgen` invokes libclang to parse C headers. It does **not** pick up
`CFLAGS_*` automatically. Pass clang flags via
`BINDGEN_EXTRA_CLANG_ARGS_<target>` — same lowercase, hyphens-or-
underscores convention as cc-rs:

```sh
export BINDGEN_EXTRA_CLANG_ARGS_aarch64_unknown_linux_ohos="\
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
export CMAKE_TOOLCHAIN_FILE_aarch64_unknown_linux_ohos="$NDK/build/cmake/ohos.toolchain.cmake"
export OHOS_ARCH_aarch64_unknown_linux_ohos=aarch64
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
