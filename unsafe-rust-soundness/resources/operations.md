# Safety contracts of common unsafe operations

A digest of the safety preconditions for unsafe operations frequently seen in Rust code. **The std rustdoc is authoritative**; this file is a working aide. When in doubt, fetch the actual `# Safety` section from <https://doc.rust-lang.org/std/...>.

For each entry, the bullets are the preconditions a `// SAFETY:` comment must discharge.

## Raw pointer dereference (`*p`, `&*p`, `&mut *p`)

- `p` is non-null.
- `p` is aligned for `T` (`mem::align_of::<T>()`).
- `p` points within a single live allocation.
- For reads: the bytes at `*p` form a properly initialised, valid `T`.
- For materialising `&T`: no `&mut T` to overlapping memory exists for the lifetime of the `&T`, and *the bytes form a valid `T` even if you never read them*.
- For materialising `&mut T`: no other reference (shared or unique) to overlapping memory exists for the lifetime of the `&mut T`.
- The compiler's aliasing model (Stacked / Tree Borrows) governs reborrows; a raw pointer obtained from `&mut x as *mut _` then re-used after `&x` was created may already be invalidated.

## `slice::from_raw_parts(data, len)` / `from_raw_parts_mut`

- `data` is non-null and aligned for `T`.
- `data` points to `len` consecutive properly initialised `T`s within a single allocation.
- The total size `len * mem::size_of::<T>()` is ≤ `isize::MAX`.
- For the returned slice's lifetime `'a`:
  - The memory must remain valid (not freed, not reallocated) for `'a`.
  - For `from_raw_parts`: no `&mut T` to any of these `T`s exists for `'a`.
  - For `from_raw_parts_mut`: no other reference (shared or unique) to any of these `T`s exists for `'a`.
- The lifetime `'a` is unbounded at the call site — easy to over-extend by accident. Bind it deliberately (e.g. tie to a `&self` lifetime).

## `str::from_utf8_unchecked(bytes)` / `String::from_utf8_unchecked`

- `bytes` is valid UTF-8.

That's the entire contract — but "valid UTF-8" includes all Unicode rules: no isolated surrogates (U+D800..U+DFFF), no overlong encodings, valid continuation bytes. If the data could possibly contain non-UTF-8, use the safe `from_utf8` (returns `Result`) instead.

## `Box::from_raw(ptr)`

- `ptr` was previously obtained from `Box::into_raw` (or equivalent — `Box::leak` then a cast).
- The allocator the `Box` will use to free is the same one the original `Box` used. (For `Box<T, A>`, `A` matters.)
- `ptr` has not been used to construct any other `Box`, `Vec`, `Rc`, etc. that would also try to free it.
- The pointee is in a state where running `Drop::drop` is sound (i.e. the `T` value is valid — not partially moved-out).

Common bug: calling `Box::from_raw` on a pointer obtained from `malloc` or a different allocator. Use `alloc::alloc::dealloc` directly instead, or `Box::from_raw_in` with a matching allocator.

## `Vec::from_raw_parts(ptr, length, capacity)`

- `ptr` was allocated by the global allocator with the same `T` and capacity.
- `T` has the same size and alignment as what `ptr` was allocated for.
- `length ≤ capacity`.
- The first `length` elements are properly initialised.
- `capacity` is the allocation's full capacity (not less).
- Same paired-allocator constraint as `Box::from_raw`.
- `capacity * mem::size_of::<T>()` is ≤ `isize::MAX`.

`Vec::from_raw_parts_in` adds an allocator argument; same rules apply against that allocator.

## `MaybeUninit::<T>::assume_init()` / `.assume_init_ref()` / `.assume_init_mut()`

- The `MaybeUninit<T>` is in a fully-initialised state — every byte that contributes to `T`'s validity invariant is set to a valid value.
- For a `T` containing padding, the padding bytes don't need specific values, but every non-padding byte does.
- For arrays / structs of `MaybeUninit<U>`, every element / field must independently be initialised.

Common bug: using `assume_init` on a `MaybeUninit<[u8; N]>` when only the first `k < N` bytes were written.

## `mem::transmute::<Src, Dst>(x)`

- `mem::size_of::<Src>() == mem::size_of::<Dst>()` (compile-time enforced).
- Every bit pattern of `x` (an `Src`) is a valid value of `Dst`.
- For types with non-trivial layout (`repr(Rust)`, generics), the layout is **not stable**. Transmuting between `repr(Rust)` types of equal size is unsound unless one is a newtype `repr(transparent)` of the other, or both are `#[repr(C)]` with identical field layouts, or one is the same type as the other with reborrowed lifetimes.
- Specifically: do not transmute between `Vec<T>` and `Vec<U>` even when `T` and `U` have the same layout — `Vec`'s field ordering is not stable.
- Reference / pointer transmutes change the lifetime / type but the *target* must still satisfy that pointer's validity at every observation.

When in doubt, prefer `mem::transmute_copy`, manual `ptr::read`, or — best — refactor to avoid transmute.

## `NonNull::new_unchecked(ptr)`

- `ptr` is non-null.

(That's the whole contract. The validity / aliasing obligations attach when you later dereference the `NonNull`, not at construction.)

## `ptr::read(src)` / `ptr::read_unaligned(src)` / `ptr::read_volatile(src)`

- `src` is non-null.
- `src` points within a single live allocation.
- `src` is aligned for `T` (relaxed for `read_unaligned`).
- `src` points to a properly initialised `T`.
- `read` performs a bitwise copy without invoking `Clone`; the original location is **not** invalidated, so if `T: !Copy` the caller is responsible for not letting the original be used or dropped (typical pattern: `mem::forget` the original, or follow with `ptr::write` to a known-good value).

## `ptr::write(dst, val)` / `ptr::write_unaligned` / `ptr::write_volatile` / `ptr::write_bytes`

- `dst` is non-null, aligned for `T` (relaxed for `_unaligned`), within a live allocation, and writable for `T`.
- The previous value at `dst` is **not dropped** by `write`. If a valid `T` was already there and needs dropping, `ptr::drop_in_place(dst)` first or call `ptr::replace`.
- `write_bytes(dst, val, count)` requires `count * size_of::<T>()` to be in-bounds and the resulting bit pattern to be a valid `T` (writing `0` to a `&mut Vec<T>` is UB — the resulting `Vec` would have invalid internal pointers).

## `ptr::copy(src, dst, count)` / `ptr::copy_nonoverlapping`

- Both `src` and `dst` are non-null and aligned for `T`.
- `src..src+count` and `dst..dst+count` each lie in a single live allocation (may be the same allocation for `copy`).
- For `copy_nonoverlapping`: the two ranges do not overlap.
- The source range contains properly initialised `T`s.
- The destination's old values are not dropped (same as `ptr::write`).

## `<[T]>::get_unchecked(i)` / `get_unchecked_mut(i)` / range variants

- `i` is in bounds for the slice (`i < self.len()` for index, `range.end <= self.len() && range.start <= range.end` for range).
- For `get_unchecked_mut`: standard `&mut`-aliasing rules at the callsite.

These are pure performance escape hatches; benchmark before using.

## `unreachable_unchecked()`

- Control flow never reaches this call.

If reached, anything can happen. The compiler is allowed to assume execution paths leading here are dead code. Used to express "this match arm is impossible because of an invariant elsewhere" — the SAFETY comment must point at that invariant.

## `hint::assert_unchecked(cond)` (1.81+)

- `cond` is true at the call site.

The compiler is allowed to optimise as if `cond` holds. If `cond` is false, UB. Use to expose invariants the optimiser can't infer; the SAFETY comment must justify why `cond` holds.

## FFI calls (`extern "C" fn` declared as `unsafe`)

The contract is whatever the C library specifies. Common sub-rules:

- Pointers passed to C must be valid and (often) live until the C call returns — or longer, if C retains them.
- Strings via `*const c_char` must be NUL-terminated. The `CStr::from_ptr` adapter has its own contract (lifetime tie-in).
- Many libraries are not thread-safe: a "global state" library (e.g. OpenSSL pre-1.1, libcurl with shared handles) requires external synchronisation.
- Returned pointers may be owned by C (do *not* `Box::from_raw`) or borrowed (do not free). Read the C docs.
- Errno / thread-local state may be clobbered by intervening calls.
- Callbacks invoked by C from foreign threads need `Send`/`Sync` discipline.

## `static mut` read / write

- No other thread is concurrently reading or writing the same `static mut` for the duration of this access.
- No other reference (`&` or `&mut`) materialised from this `static mut` is live for the duration of this access.

In multithreaded programs, this is essentially impossible to uphold without external synchronisation. Modern Rust (1.78+) lints `static_mut_refs`; treat any `static mut` access as *probably unsound* and refactor to `Mutex`, `RwLock`, atomics, or `OnceLock`.

## `Pin::new_unchecked(ptr)`

- The pointee will not be moved (in the `mem::swap` sense) for the rest of its existence.

For `T: Unpin`, prefer `Pin::new` (safe). For `!Unpin` types, the caller commits to honouring pin projection rules — see <https://doc.rust-lang.org/std/pin/index.html#projections-and-structural-pinning>.

## `unsafe impl Send for T` / `unsafe impl Sync for T`

`Send`: it is sound to transfer ownership of `Self` to another thread.
`Sync`: it is sound to share `&Self` between threads (equivalent to `&Self: Send`).

For each non-`Send`/non-`Sync` field, justify *why* its presence does not invalidate the claim:

- Raw pointer with unique ownership of a `Send` allocation: ✓ (e.g. typical smart-pointer).
- `Cell` / `UnsafeCell` with all access serialised through a `Mutex` field: ✓ if true.
- `Rc<T>`: ✗ for `Send` — `Rc` is fundamentally not `Send` because cloning is non-atomic.
- `Cell<T>`: ✗ for `Sync` — `Cell` allows mutation through `&`, breaking thread-safety.

A `unsafe impl !Send` (negative impl, nightly) is a different beast — opting *out* — and isn't covered here.
