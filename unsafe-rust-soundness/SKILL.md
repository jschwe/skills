---
name: unsafe-rust-soundness
description: Audit Rust `unsafe` blocks, functions, and trait impls for soundness — verify every unsafe operation has a discharged `// SAFETY:` justification and every `unsafe fn` documents every precondition it relies on. Trigger when reviewing unsafe Rust code, auditing FFI bindings, checking SAFETY comments, validating safety preconditions, or asked things like "is this unsafe block sound", "review the unsafe code", "check the SAFETY comments", "is this UB", "audit unsafe rust".
---

# unsafe-rust-soundness

Systematic review of Rust `unsafe` code. The goal is to confirm two things:

1. **Every `unsafe` block** has a `// SAFETY:` comment whose justifications discharge *every* safety precondition of *every* unsafe operation in the block, and those justifications are verifiable from the surrounding code.
2. **Every `unsafe fn`** has a `# Safety` doc section that lists *every* precondition the body relies on, no fewer (sufficiency) and ideally no more (necessity).

The same logic applies to `unsafe impl` (the trait's safety contract is the precondition list) and `unsafe trait` definitions (their `# Safety` doc *is* the contract that callers / impls discharge).

## What "sound" means

A block of Rust code is sound if no input that satisfies its public type signature can cause Undefined Behavior. The safe/unsafe boundary is where soundness reasoning lives:

- Inside a safe fn, every `unsafe { ... }` block must establish that *no UB can occur at this callsite*, regardless of how the safe fn is called.
- Inside an `unsafe fn`, the body may rely on caller-provided invariants — but those invariants **must be documented in `# Safety`**. Anything the body assumes without documenting is a soundness bug.

Soundness is *local given the contract*. A reviewer's job is to check both the local reasoning and the contract.

## Workflow

1. **Locate** all `unsafe` items in the project (blocks, fns, impls, traits).
2. **For each unsafe block:** enumerate unsafe operations → fetch each operation's safety contract → check `// SAFETY:` discharges each item → trace each justification to where the invariant is established.
3. **For each `unsafe fn` definition:** check `# Safety` lists every precondition the body relies on (sufficiency) and is not over-restrictive (necessity).
4. **For each `unsafe impl Trait for T`:** check the impl satisfies the trait's documented safety contract, with a `// SAFETY:` comment explaining why.
5. **Report** per-item verdict (sound / undocumented / unsound / needs-more-info) with file:line.

## Step 1 — Locate unsafe code

```sh
# Every unsafe span
rg -n '\bunsafe\b' --type rust

# Unsafe trait impls (manual review-bait — not rare for these to be wrong)
rg -n '^unsafe impl' --type rust

# Static muts (always suspicious in multithreaded code)
rg -n '\bstatic mut\b' --type rust
```

Lint-driven discovery is preferable when the project compiles, because clippy enumerates exactly the items needing review:

```sh
cargo clippy --all-targets --all-features -- \
  -W clippy::undocumented_unsafe_blocks \
  -W clippy::multiple_unsafe_ops_per_block \
  -W clippy::missing_safety_doc \
  -W clippy::unnecessary_safety_comment \
  -W clippy::unnecessary_safety_doc \
  -W unsafe_op_in_unsafe_fn 2>&1
```

- `undocumented_unsafe_blocks` — unsafe block with no `// SAFETY:`.
- `missing_safety_doc` — public `unsafe fn` with no `# Safety` section.
- `multiple_unsafe_ops_per_block` — encourages one unsafe op per block, so each gets its own SAFETY comment.
- `unsafe_op_in_unsafe_fn` — body of `unsafe fn` is no longer implicitly unsafe; each op needs its own `unsafe { … }` with its own SAFETY comment. This is the default in edition 2024; warn-by-default in 2021. **Always treat `unsafe fn` bodies as if this lint is enabled** — don't accept "the whole body is unsafe so one comment covers it".

## Step 2 — Audit one unsafe block

### 2a. Enumerate the unsafe operations

The block is unsafe because it does *some* of these. Pin down which:

- Dereference of raw pointer: `*p`, `&*p`, `&mut *p`, field access `(*p).x`, method call through `*p`.
- Call to `unsafe fn` (any function with `unsafe` in its declaration, including FFI / `extern "C"` / `extern "Rust"` items).
- Read/write of `static mut`.
- Read of a `union` field (write is safe, read is unsafe).
- Call to an `unsafe` trait method (some traits like `GlobalAlloc` declare individual methods unsafe).

Most "library" unsafe (`get_unchecked`, `assume_init`, `transmute`, `from_raw_parts`, `from_utf8_unchecked`, …) reduces to "call to unsafe fn"; the contract lives in that function's rustdoc.

If the block contains *multiple* independent unsafe ops, each needs its own justification. Prefer splitting the block one-op-per-block (as `clippy::multiple_unsafe_ops_per_block` recommends) so each `// SAFETY:` is unambiguous about which op it covers.

### 2b. Pull the safety contract for each operation

- **Unsafe fn calls (incl. std):** read its rustdoc, specifically the `# Safety` section. For std, use `https://doc.rust-lang.org/std/...` or `rustup doc --std`. The contract is enumerated bullets like "ptr must be aligned for `T`", "len ≤ allocation", etc. Treat each bullet independently.
- **Raw pointer deref:** the contract is fixed and substantial. The pointer must be (a) non-null, (b) aligned for `T`, (c) point inside a single live allocation, (d) point to a properly initialised `T` for reads, (e) be uniquely accessible (no aliasing reference) for the duration of any `&mut` materialised, or (f) be free of concurrent `&mut` for any `&` materialised. Reading uninitialised memory through `&T` is UB even if you never inspect the bytes.
- **`static mut` access:** no concurrent access of any kind for the duration of access. In a multithreaded program, this is essentially untenable without external synchronisation.
- **Union field read:** the chosen field's bit pattern must be a valid `T` for that field's type. (Unions don't track which field was written.)
- **Custom unsafe trait methods (e.g. `Allocator::deallocate`):** read the trait's per-method `# Safety` section.

For std-specific contracts, see [resources/operations.md](resources/operations.md) — covers `slice::from_raw_parts`, `str::from_utf8_unchecked`, `Box::from_raw`, `Vec::from_raw_parts`, `MaybeUninit::assume_init`, `mem::transmute`, `NonNull::new_unchecked`, `ptr::read`/`write`/`copy`, `get_unchecked`, `unreachable_unchecked`, etc.

### 2c. Verify the `// SAFETY:` comment discharges each contract item

Every bullet from 2b must map to a justification in the SAFETY comment. Each justification falls into one of:

- "X holds because we just constructed it that way" — must be traceable to the construction in the same scope.
- "X holds because the caller of this fn guaranteed it" — only valid inside an `unsafe fn`, and the obligation must be in that fn's `# Safety` section.
- "X holds because invariant Y of struct Z is maintained" — Z must have the invariant documented somewhere reachable (struct doc, dedicated `Invariants:` doc section, comment on the field).

Red flags in SAFETY comments:

- Boilerplate: `// SAFETY: trust me`, `// SAFETY: this is safe`, `// SAFETY: see above`.
- Names *one* of several preconditions and silently omits the rest.
- Justification only holds on the happy path (e.g. assumes no early-return / panic / `?` left partial state mid-block).
- Reasoning depends on data not yet observed (e.g. `len` from an FFI call) without a check.
- Quotes a condition that is *not* in the function's actual `# Safety` doc — could indicate the reviewer is checking against a stale or wrong contract.

### 2d. Trace each justification

For each invariant the SAFETY comment cites, follow it to where it's established. Examples:

- "ptr is non-null" → where was `ptr` produced? `Box::into_raw` / `Box::leak` (always non-null ✓), `NonNull::as_ptr` (✓), an FFI return value (must be checked — ✗ if unchecked), `ptr::null().offset(n)` (depends on n), `&x as *const _` (✓).
- "len fits in the allocation" → trace `len`. Constant (✓), result of `min(a, b)` against allocation size (✓), function argument (push to `# Safety` of the enclosing `unsafe fn`), value from external source (must be validated).
- "no aliasing" → are there other live references into the same allocation in scope? Watch for materialising `&mut` while a `&` is live (or vice versa), reborrows through raw pointers that re-enter Rust reference semantics, and references obtained via `slice::from_raw_parts` overlapping a `&mut` slice.

If you can't trace an invariant to its establishment, the block is **needs-more-info**, not "sound".

## Step 3 — Audit an `unsafe fn` definition

```rust
/// Reads a `T` from `ptr`.
///
/// # Safety
///
/// - `ptr` must be non-null and aligned for `T`.
/// - `ptr` must point to a properly initialised `T`.
/// - For the duration of the call, no other reference may alias `*ptr`,
///   and `*ptr` must not be mutated through another pointer.
pub unsafe fn my_read<T>(ptr: *const T) -> T { … }
```

Audit by:

1. **Body operations.** Treat the body as you would any unsafe block (Step 2a–d). Distinguish what's discharged locally vs. punted to the caller.
2. **Contract match.** Each precondition the body needs from the caller must appear in `# Safety`. Each item in `# Safety` must be load-bearing.
3. **Hidden assumptions.** Common omissions:
   - **Lifetime / borrow scope.** "Returned reference is valid as long as `*ptr` is" — the type signature usually can't enforce this; if not documented and not enforced by the signature, the fn is unsound.
   - **Drop-time invalidation.** Any raw pointer the caller holds into a `Box`/`Vec`/`String` is invalidated when the owner drops; if `unsafe fn` returns such a pointer, document the lifetime constraint.
   - **Panic safety.** If the body can panic mid-way (e.g. between writing one field and another), can the caller observe partially-constructed state via a raw pointer they kept? If yes, document or use `catch_unwind`/abort guards.
   - **Thread-safety.** If the fn touches an inner pointer also accessible from `&self` on another thread, document the synchronisation requirement.
   - **Pointer provenance.** "ptr must be derived from the same allocation as `base`" — `wrapping_add`/`offset` carry provenance.

### Sufficiency vs. necessity

- **Sufficiency:** assuming all `# Safety` bullets, can a sufficiently malicious caller still trigger UB? If yes, the doc is incomplete.
- **Necessity:** is each bullet actually needed by the body? If you can strip a bullet and the body is still sound, the bullet is over-restrictive — callers will work around or ignore it, and the next refactor that *does* need it will silently introduce UB.

The right standard is **sufficient and minimal**.

### `pub` vs. crate-internal `unsafe fn`

A `pub unsafe fn` is part of the crate's public API; `# Safety` is mandatory. A `pub(crate)` or private `unsafe fn` may rely on local conventions — but only if the conventions are *documented somewhere*. "We only call this from `foo()` so the precondition holds" is not a contract; the *next* caller will get it wrong.

## Step 4 — `unsafe impl` for a trait

```rust
// SAFETY: MyBox<T> uniquely owns its allocation; T: Send means the contained
// value is safe to transfer; we have no shared interior mutability that
// would make sending across threads observable from the original thread.
unsafe impl<T: Send> Send for MyBox<T> {}
```

For each `unsafe impl Trait for Type`:

1. **Find the trait's safety contract.** Common cases:
   - `Send`: it is sound to transfer ownership of `Self` across thread boundaries.
   - `Sync`: it is sound to share `&Self` across thread boundaries (i.e. `&Self: Send`).
   - `GlobalAlloc` / `Allocator`: per-method `# Safety` sections (alignment, layout, paired alloc/dealloc, etc.).
   - Custom `unsafe trait`: read its definition's `# Safety` section. If the trait is declared `unsafe trait` but has no `# Safety` doc, that's already a finding — the trait author owes you a contract.
2. **Verify the impl satisfies it.** For `Send`/`Sync` especially, walk every field of `Type`:
   - If all fields are `Send`/`Sync`, the auto-impl applies — you don't need `unsafe impl` at all. Its presence likely indicates a *negative* component (raw pointer, `*mut T`, `Cell`, etc.).
   - For each non-`Send`/non-`Sync` field, give a *concrete* reason: "raw pointer is the unique owner of a heap allocation that contains only `T: Send`", "interior `Cell` is only mutated under `Mutex`", "PhantomData<NotSend> exists only to influence variance, no actual NotSend value is held".
   - "We don't actually use it across threads in practice" is **not** a valid reason — `Send`/`Sync` are unconditional capabilities.
3. **Drop check / variance.** If `Type` uses `PhantomData` or holds raw pointers, check its drop check and variance posture matches the safety claim. The Nomicon's [PhantomData chapter](https://doc.rust-lang.org/nomicon/phantom-data.html) is the reference.

## Tools

- **Clippy lints** (Step 1): static enumeration of undocumented blocks/fns.
- **`cargo +nightly miri test`**: runtime UB detection (out-of-bounds, uninit reads, aliasing violations under Stacked Borrows / Tree Borrows, data races) for whatever the test suite exercises. Slow but catches what humans miss. Caveats: can't run FFI; only finds UB on covered paths.
- **`-Zsanitizer=address`/`thread`** (nightly): production-grade UB sanitizers; useful for FFI-heavy code Miri can't enter.
- **`cargo expand`**: when unsafe is generated by a macro, expand to see the actual unsafe ops.
- **Loom**: concurrency permutation testing for atomics/lock-free code.
- **Kani**: bounded model checking — appropriate for narrowly-scoped, atomics-heavy invariants; usually overkill for a one-off review.

These are *complements*, not substitutes, for source-level review. Miri can't prove soundness, only find specific UB on tested paths.

## Common UB patterns to watch for

See [resources/ub-patterns.md](resources/ub-patterns.md). Highlights:

- **Aliasing violations** — `&mut` materialised while `&` is live (or vice versa), even if the references are derived through raw pointers.
- **Lifetime extension via raw pointer** — `&*ptr` produces a reference with whatever lifetime is inferred; if that lifetime outlives the underlying allocation, UB.
- **Validity invariants on uninit memory** — even *creating* a `&T` to uninitialised bytes (without reading) is UB if the bytes don't form a valid `T`.
- **`transmute` size or layout mismatches** — `repr(Rust)` types have no guaranteed layout; transmuting two `repr(Rust)` types is brittle even when sizes match.
- **FFI string lifetimes** — `CStr`/`*const c_char` returned by C may be freed by the next FFI call.
- **`Pin` projection** — projecting through `Pin<&mut T>` to a non-`Unpin` field requires `unsafe` and structural-pinning discipline.
- **`Send`/`Sync` over-claims** — manually impling these on types containing `Rc`, `Cell`, raw pointers without justifying every component.
- **Drop ordering** — `Drop` runs in declaration order for fields, reverse for stack locals; raw pointers obtained from a value can be dangling immediately after that value's drop.

## Authoritative references

- **The Rustonomicon** — <https://doc.rust-lang.org/nomicon/>. The book on unsafe Rust.
- **Reference: behavior considered undefined** — <https://doc.rust-lang.org/reference/behavior-considered-undefined.html>. Definitive list of what's UB.
- **std rustdoc** — every `unsafe fn` documents its contract under `# Safety`. The contract there is authoritative; this skill's [resources/operations.md](resources/operations.md) is a digest, not a substitute.
- **std source** at <https://doc.rust-lang.org/src/...> when the rustdoc is ambiguous.
- **Rust UCG (Unsafe Code Guidelines)** — <https://rust-lang.github.io/unsafe-code-guidelines/>. Work-in-progress formalisation; useful for nuanced questions where the Nomicon and Reference are vague.

## Reporting format

For each item reviewed, produce one entry. Group by verdict at the end so the user can triage `unsound` first, `undocumented` next, etc.

```
file.rs:line — <unsafe block | unsafe fn name | unsafe impl Trait for Type>
  Verdict:   sound | undocumented | unsound | needs-more-info
  Operations: <unsafe ops in the block / body>
  Findings:  <what's missing, wrong, or unverifiable — one bullet per issue>
  Suggested SAFETY comment / # Safety bullets: <draft, if missing or weak>
```

A short summary line at the end ("4 sound, 1 undocumented, 1 unsound") helps the user know how much remediation is needed.
