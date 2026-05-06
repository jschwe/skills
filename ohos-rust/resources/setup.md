# ohos-rust — setup walkthrough

Long-form companion to SKILL.md. Read this when something does not work
or when the SDK layout is unfamiliar.

## SDK layout

A fresh standalone OHOS SDK (`ohos-sdk-*.zip`) unpacks roughly as:

```
ohos-sdk/
└── <host_os>/                  # darwin / linux / windows / ohos
    └── native/                 # = $OHOS_SDK_NATIVE
        ├── build/              # CMake toolchain files (ohos.toolchain.cmake)
        ├── docs/
        ├── llvm/
        │   ├── bin/clang                                  # raw cross-compiler
        │   ├── bin/clang++
        │   ├── bin/<rust-triple>-clang                    # POSIX-shell wrapper, preferred linker
        │   ├── bin/<rust-triple>-clang++                  # e.g. aarch64-unknown-linux-ohos-clang
        │   ├── bin/llvm-ar
        │   ├── bin/llvm-ranlib
        │   └── lib/<clang-triple>/libc++_shared.so
        ├── sysroot/            # headers + libs the compiler needs
        ├── ndk_system_capability.json
        └── oh-uni-package.json # contains "apiVersion" — useful to identify the level
```

Some SDK distributions (e.g. DevEco Studio managed OpenHarmony SDKs) ship multiple API levels under one root:

```
ohos-sdk/
├── 11/native/
├── 12/native/
└── 14/native/
```

Unless instructed otherwise, pick the highest numeric `<api>` directory or `default` and point `$OHOS_SDK_NATIVE` at
its `native/` child.

## Verifying the toolchain

```sh
"$OHOS_SDK_NATIVE/llvm/bin/clang" --version
# Should print Huawei/OHOS-flavored clang, e.g.
# OpenHarmony (...) clang version 15.0.4 ...
# Target: x86_64-apple-darwin (or your host)
```

Sanity-check that the OHOS targets exist as known clang targets:

```sh
"$OHOS_SDK_NATIVE/llvm/bin/clang" --target=aarch64-linux-ohos -print-effective-triple
# → aarch64-unknown-linux-ohos
```

## rustup targets

```sh
rustup target list --installed | grep ohos
rustup target add aarch64-unknown-linux-ohos
```

If `rustup target add` says "error: toolchain '...' does not contain
component 'rust-std' for target 'aarch64-unknown-linux-ohos'", your
rustup is older than ohos-target stabilization (1.78). Fix:

```sh
rustup self update
rustup update stable
rustup default stable
```

Do **not** reach for `-Zbuild-std` or a rustc fork — the stable
prebuilt rust-std works.

## Why the per-triple wrapper instead of plain clang

Rust's prebuilt `*-unknown-linux-ohos` rust-std is compiled against the
OHOS sysroot, but rustc itself does not know where that sysroot lives on
your machine. clang, used as the linker, also doesn't know unless told.
The `<rust-triple>-clang` wrappers in `$OHOS_SDK_NATIVE/llvm/bin/` are
small POSIX shell scripts that call the underlying `clang` with
`--target=<clang-triple>` and `--sysroot=$NDK/sysroot` (plus
`-march=`/`-mfloat-abi=` for armv7) prepended to whatever cargo passes.
So pointing `CARGO_TARGET_*_LINKER` at the wrapper eliminates the need
for any `link-arg=--target=...` / `link-arg=--sysroot=...` rustflags.

Skipping the wrapper (or skipping the equivalent rustflags on Windows)
typically surfaces as one of:

- `ld: cannot find -lc` / `cannot find crt1.o`
- `undefined reference to __libc_start_main`
- `error: linking with cc failed: ... unable to find library -lgcc`

All of those mean clang fell back to the host system's libc/crt and
failed.

## Common linker errors

| Error                                                          | Likely cause                                              |
|----------------------------------------------------------------|-----------------------------------------------------------|
| `cannot find -lc` / `cannot find crt1.o`                       | `--sysroot` flag missing or wrong path                    |
| `error: unknown target triple 'aarch64-unknown-linux-ohos'`    | clang too old, or `--target=` set to the Rust triple instead of the clang triple |

## Per-target env-var blocks

The block in SKILL.md is the minimum. A more thorough version that also
locks down `cc-rs` (so any *-sys crate hitting cargo's build script uses
the OHOS toolchain) is in c-deps.md.

## Verifying the produced binary

```sh
file target/aarch64-unknown-linux-ohos/release/myapp
# → ELF 64-bit LSB pie executable, ARM aarch64, ... dynamically linked,
#   interpreter /system/bin/ld-musl-aarch64.so.1 ...
```

The interpreter line — `/system/bin/ld-musl-aarch64.so.1` — confirms it's
a real OHOS binary (musl-based), not glibc. If you see
`/lib64/ld-linux-x86-64.so.2` or similar, you accidentally produced a
host binary; the linker env var is not taking effect.

```sh
"$OHOS_SDK_NATIVE/llvm/bin/llvm-readelf" -d \
    target/aarch64-unknown-linux-ohos/release/myapp | grep NEEDED
# Should list libc.so, libc++_shared.so, ld-musl-aarch64.so.1, ...
```
