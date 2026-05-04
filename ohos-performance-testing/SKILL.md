---
name: ohos-performance-testing
description: Profile OpenHarmony / OHOS / HarmonyOS apps with hiperf (CPU sampling, callchains, flamegraphs). Trigger when the user mentions hiperf, OpenHarmony performance, profiling an OHOS or HOS device, or analysing a hiperf.data capture.
---

## HiPerf

hiperf is a command-line tool provided to capture performance data of a specific program or the entire system, like the kernel's perf tool. It can be used to analyze the performance of OpenHarmony applications and identify bottlenecks. Its usage is similar to the `perf` tool.
See @ohos-performance-testing/resources/hiperf.md for more details.

## Talking to the device

This skill drives the device through `hdc` — see the `hdc` skill for the
device-connector itself (in particular the silent `hdc shell` exit-code
behavior, which matters when scripting hiperf captures), and
`@hdc/resources/remote-hdc.md` when the device is attached to a different
host than the agent.
