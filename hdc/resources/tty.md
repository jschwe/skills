# hdc — TTY allocation and window-size workaround

`hdc shell` (no args, interactive) **does** allocate a real PTY on the
device — `isatty(0/1/2)` returns 1 inside the shell. But it does
**not** propagate the host terminal's window size to that PTY.
`TIOCGWINSZ` returns `rows=0 cols=0`, and unlike SSH, hdc does not
send `SIGWINCH` / forward window-size updates when the host terminal
resizes.

Symptoms:

- Curses / TUI apps (kibi, helix, vim, htop, less full-screen mode) launch
  but render a **black / blank screen** — they cleared the screen and
  then drew zero rows of content.
- Apps that fall back to `\x1b[6n` (DSR — Device Status Report) for size
  detection get a stale or capped reply: in observed behavior the cursor
  maxes out around row 10 col 1, and the reply arrives well after a
  500 ms timeout, so the fallback fails too.

This is independent of TERM (often `ansi` on OHOS). It's an hdc-side limitation.

## Diagnostic probe

If you want to verify on a given device, this small Rust program
reports `isatty`, `TIOCGWINSZ`, and the DSR fallback in one go. Build
it for the device with the `ohos-rust` skill and push under
`/data/local/tmp/`:

```rust
// Cargo.toml: libc = "0.2"
use std::io::Write;
use std::os::fd::AsRawFd;

fn main() {
    for (name, fd) in [
        ("stdin",  std::io::stdin().as_raw_fd()),
        ("stdout", std::io::stdout().as_raw_fd()),
        ("stderr", std::io::stderr().as_raw_fd()),
    ] {
        let mut ws: libc::winsize = unsafe { std::mem::zeroed() };
        let r = unsafe { libc::ioctl(fd, libc::TIOCGWINSZ, &mut ws) };
        if r == 0 {
            println!("{name}: rows={} cols={}", ws.ws_row, ws.ws_col);
        } else {
            println!("{name}: ioctl failed: {}", std::io::Error::last_os_error());
        }
    }
    println!("isatty 0/1/2 = {} {} {}",
        unsafe { libc::isatty(0) }, unsafe { libc::isatty(1) }, unsafe { libc::isatty(2) });

    // DSR fallback — needs interactive shell to receive the reply.
    print!("\x1b[6n");
    std::io::stdout().flush().unwrap();
    let mut buf = [0u8; 32];
    unsafe {
        let mut fds: libc::fd_set = std::mem::zeroed();
        libc::FD_SET(0, &mut fds);
        let mut tv = libc::timeval { tv_sec: 0, tv_usec: 500_000 };
        if libc::select(1, &mut fds, std::ptr::null_mut(), std::ptr::null_mut(), &mut tv) > 0 {
            let n = libc::read(0, buf.as_mut_ptr() as *mut _, buf.len());
            println!("DSR reply ({n} bytes): {:?}", &buf[..n.max(0) as usize]);
        } else {
            println!("DSR: no reply within 500 ms");
        }
    }
}
```

A healthy SSH/PTY shell would report sensible row/col numbers and a
DSR reply matching the cursor's actual position. Over `hdc shell`,
expect `rows=0 cols=0` and a missed/garbled DSR.

## Workaround: set the size manually with `TIOCSWINSZ`

OHOS ships no `stty`, no `tput`, no `resize` — none of the usual
terminal-utility paths exist. Cross-compile a tiny `setwinsize`
helper instead and push it once per device:

```rust
// Cargo.toml: libc = "0.2"
use std::os::fd::AsRawFd;

fn main() -> std::io::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let fd = std::io::stdin().as_raw_fd();
    let mut ws: libc::winsize = unsafe { std::mem::zeroed() };
    match args.len() {
        1 => {
            if unsafe { libc::ioctl(fd, libc::TIOCGWINSZ, &mut ws) } != 0 {
                return Err(std::io::Error::last_os_error());
            }
            println!("rows={} cols={}", ws.ws_row, ws.ws_col);
        }
        3 => {
            ws.ws_row = args[1].parse().expect("ROWS u16");
            ws.ws_col = args[2].parse().expect("COLS u16");
            if unsafe { libc::ioctl(fd, libc::TIOCSWINSZ, &ws) } != 0 {
                return Err(std::io::Error::last_os_error());
            }
            println!("set: rows={} cols={}", ws.ws_row, ws.ws_col);
        }
        _ => { eprintln!("usage: setwinsize [ROWS COLS]"); std::process::exit(2); }
    }
    Ok(())
}
```

Build with the `ohos-rust` skill, push to `/data/local/tmp/bin/`, then
inside an interactive `hdc shell`:

```sh
/data/local/tmp/bin/setwinsize 40 120   # match your host terminal roughly
/data/local/tmp/bin/setwinsize          # read back what's set
your-tui-app                            # now renders
```

The size persists for the lifetime of the shell session. If the host
terminal resizes, rerun `setwinsize` with the new numbers — hdc won't
forward the SIGWINCH for you.

## Why not `script` / `socat` / `screen` / `tmux`

None of these are present on stock OHOS builds. Even if you cross-
compile one, it has the same problem at its outer boundary: the PTY it
allocates inherits the 0×0 size from its parent (the hdc shell). You'd
still need `TIOCSWINSZ` somewhere in the chain.

## Non-TTY commands

If the host invocation is `hdc shell <cmd>` (one-shot), there is no PTY
at all — `isatty` returns 0, all three FDs are pipes. TUI apps will
exit immediately or misbehave; only line-oriented tools work. For
running TUI apps non-interactively from a script, you'd need a
PTY-forging wrapper (e.g. a small Rust binary that calls `forkpty`
device-side) — but for one-off edits, `hdc file recv` / edit on host /
`hdc file send` is usually less work than fighting the relay.
