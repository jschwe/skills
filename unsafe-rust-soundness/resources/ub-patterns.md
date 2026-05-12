# Common UB patterns in Rust unsafe code

Patterns that look correct on a quick read but trigger Undefined Behavior. Use this as a checklist when reviewing unsafe code.

## 1. Aliasing violation through reborrow

Rust's aliasing model (Stacked Borrows / Tree Borrows) is enforced even when you "go via" a raw pointer. Materialising a `&mut T` while a `&T` to overlapping memory is live is UB regardless of whether it's done directly or through `*mut T`.

```rust
let mut x = 0u32;
let r = &x;            // shared reference live
let p = &x as *const u32 as *mut u32;
unsafe { *p = 1 };     // UB: writes through p while r aliases
let _ = *r;
```

**Watch for:** raw-pointer round-trips (`&x as *const _ as *mut _`), `transmute::<&T, &mut T>`, `UnsafeCell`-less interior mutation, slice splits not done via `split_at_mut`.

## 2. Lifetime extension via raw pointer

`&*ptr` produces a reference whose lifetime is whatever the surrounding context infers — easily longer than the underlying allocation actually lives.

```rust
fn dangling() -> &'static str {
    let s = String::from("hi");
    let p = s.as_ptr();
    unsafe { std::str::from_utf8_unchecked(std::slice::from_raw_parts(p, s.len())) }
    // s drops at end of fn; returned &'static str is dangling
}
```

**Watch for:** unbounded lifetimes from `from_raw_parts` / `&*ptr`, `transmute::<&'a T, &'static T>`, returning references into local data via raw-pointer detours.

## 3. Validity invariant on uninitialised memory

Even *creating* a `&T` to memory that doesn't satisfy `T`'s validity invariant is UB — you don't have to read.

```rust
let m: MaybeUninit<&u32> = MaybeUninit::uninit();
let r: &&u32 = unsafe { m.assume_init_ref() };  // UB: &u32 must point at valid u32
```

```rust
let m: MaybeUninit<bool> = MaybeUninit::uninit();
let _ = unsafe { m.assume_init() };             // UB: bool must be 0 or 1
```

**Watch for:** `MaybeUninit::assume_init` / `assume_init_ref` / `assume_init_mut` on partially or never-written buffers, `mem::zeroed::<T>()` for any `T` whose all-zeros bit pattern isn't valid (references, `NonZeroU32`, `bool` is fine but `&T` isn't).

## 4. Reading padding bytes

Reading uninitialised padding bytes through any typed access is UB. `ptr::read` of a `#[repr(C)]` struct with padding from a buffer where the padding wasn't initialised is UB even if every non-padding field was set.

**Watch for:** `ptr::read::<T>` / `transmute::<[u8; N], T>` from a buffer not fully initialised; `&[u8]` views obtained from `as_bytes`-style reinterpretation of structs with padding.

## 5. `transmute` between `repr(Rust)` types

`#[repr(Rust)]` (the default) gives the compiler complete freedom over field ordering and padding. Two structs with "the same fields" can have different layouts.

```rust
struct A { x: u8, y: u32 }
struct B { x: u8, y: u32 }
let a = A { x: 1, y: 2 };
let b: B = unsafe { mem::transmute(a) };  // unsound — layouts not guaranteed equal
```

**Watch for:** transmuting between user-defined types lacking `#[repr(C)]` / `#[repr(transparent)]`, transmuting `Vec<T> ↔ Vec<U>`, transmuting `Box<dyn Trait>` to anything.

## 6. FFI string lifetime

A `*const c_char` returned by C may point to:

- a static C-string (lives forever), or
- a thread-local buffer overwritten by the next call (e.g. `strerror`), or
- a heap allocation owned by C and freed by the next library call (e.g. some `libcurl` getters), or
- a heap allocation the caller must free (`strdup`).

**Watch for:** `CStr::from_ptr` on returned C strings without checking the C function's documented ownership; storing such a `&CStr` past the next FFI call.

## 7. `Pin` projection violations

Projecting through `Pin<&mut T>` to a field requires the field to be either *structurally pinned* (you commit to never moving it) or `Unpin`. Mixing the two improperly is UB.

```rust
struct S { a: Inner /* should be pinned */, b: u32 }
unsafe fn get_a_mut(p: Pin<&mut S>) -> &mut Inner {
    // UB if Inner: !Unpin and we previously projected it as Pin<&mut Inner> —
    // by handing out &mut Inner here, the caller can mem::swap and move it
    &mut Pin::into_inner_unchecked(p).a
}
```

**Watch for:** mixing `Pin::new_unchecked` with safe `&mut` projection of `!Unpin` fields; pin projection without a documented "this field is structurally pinned" decision.

## 8. `Send`/`Sync` over-claim

`unsafe impl Send for MyType {}` where `MyType` contains a non-`Send` field without justification.

Common offenders:

- Raw pointer to thread-local data.
- `Rc<T>` (never `Send`, the refcount isn't atomic).
- `*mut T` to data accessible from another thread without synchronisation.
- `Cell<T>` / `RefCell<T>` impl'd `Sync` (these are `!Sync` by design).

**Watch for:** `unsafe impl Send` / `Sync` on types containing raw pointers without naming what they point at and who owns it.

## 9. Drop order / dangling pointer after drop

Stack locals drop in reverse declaration order; struct fields drop in declaration order. Raw pointers obtained from a value are dangling immediately after that value drops.

```rust
let owned = vec![1, 2, 3];
let p = owned.as_ptr();
drop(owned);
unsafe { let _ = *p; }   // UB: dangling
```

In structs with raw pointers, ensure the pointed-at owner outlives the pointer (or use `PhantomData` to record the borrow).

**Watch for:** `Drop` implementations using `Box::from_raw` / manual dealloc that conflict with field-drop order; raw pointers stored in long-lived structs that point at short-lived owners.

## 10. Pointer provenance / out-of-bounds offset

`ptr.offset(n)` / `ptr.add(n)` requires the result to remain within the same allocation as `ptr` (with one-past-the-end allowed). "Just doing arithmetic" without an actual deref is *still* UB on overflow / out-of-bounds.

```rust
let arr = [0u8; 4];
let p = arr.as_ptr();
unsafe { p.add(8); }    // UB: out of bounds, even without deref
```

Use `wrapping_add` if you genuinely need pointer-as-integer arithmetic; deref then becomes the soundness boundary.

**Watch for:** `offset` / `add` / `sub` with values not provably in-bounds; arithmetic on pointers from different allocations.

## 11. Data races on non-atomic types

Concurrent unsynchronised access (one of which is a write) on the same memory location, where the access isn't via an atomic, is UB. This includes:

- Two threads each holding `*mut T` to the same `T`, both writing.
- A `Mutex<T>` whose contents are accessed via raw pointers bypassing the lock.
- `static mut` read from one thread while another writes (without `unsafe { … }` and a synchronisation primitive).

**Watch for:** lock-free claims with non-atomic field accesses; `unsafe impl Sync` enabling multi-threaded `&self` access to non-atomic interior state.

## 12. Calling a Rust function with the wrong ABI through a function pointer

Rust function ABI is unstable. Casting a `fn(A) -> B` to a `fn(C) -> D` and calling it is UB unless layouts are `#[repr(C)]`-stable AND the calling convention matches. FFI callbacks must be `extern "C"`.

**Watch for:** transmuting function pointers; passing Rust default-ABI functions to C as callbacks.

## 13. Returning `&T` to data with a shorter validity than `T`

Even `&MaybeUninit<T>` is fine, but `&T` requires `T`'s full validity invariant *for as long as the reference is live*. If the underlying memory is concurrently mutated (e.g. in a lock-free read), the reader may observe a torn value while still holding `&T`.

**Watch for:** "publishing" a value via raw pointer write while another thread already holds a `&T` to it; lock-free reads that materialise a `&T` instead of `ptr::read_volatile`.

## 14. UTF-8 invariant on `&str`

`&str` requires its bytes are valid UTF-8 *as long as the reference is live*, not just at construction. Mutating the bytes through a `*mut u8` to non-UTF-8 while a `&str` is alive is UB.

**Watch for:** `String::as_mut_vec` followed by inserting non-UTF-8 bytes; in-place encoding conversions that briefly leave invalid UTF-8.

## 15. Forgetting `repr(transparent)` for `NonZero*` / `Option<NonZero*>` niche

Niche optimisation: `Option<&T>`, `Option<NonNull<T>>`, `Option<NonZeroU32>` etc. occupy the same size as the inner type by using a forbidden bit pattern (zero) as `None`. `transmute::<Option<&T>, &T>` of a `Some(x)` value is OK; of a `None` it's UB (you'd produce a null reference).

**Watch for:** `transmute` from `Option<NonZero*>` / `Option<&T>` without first checking the value is `Some`; assuming layout equality without it.

---

When in doubt, reach for [Miri](https://github.com/rust-lang/miri):

```sh
cargo +nightly miri test
```

Miri can't *prove* soundness, but it catches most concrete instances of these patterns on whatever paths the test suite exercises.
