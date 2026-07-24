# S100 local-AI track

The RDK S100 is powerful enough to be an AI host, not merely a navigation
computer. PawGuide will keep the inference location swappable until the actual
board is benchmarked under the same power, thermal and network conditions used
on the robot.

## MVP decision

For the first moving MVP:

- the Pixel owns ring audio, push-to-talk state, the 500 ms safety heartbeat
  and the immediate STOP path;
- the Pixel runs the primary local language model and TTS;
- the S100 owns the safety gateway, DimOS, mapping, planning and Go2 WebRTC;
- deterministic schema validation and the waypoint allowlist sit between every
  model and motion;
- the S100 BPU may run perception, but no model may own heartbeat, STOP-latch
  reset, arming or speed limits.

This is a deployment default, not an architectural restriction. The phone can
later send the transcript to a model endpoint on the S100 and receive the same
strict command proposal. Ring handling and the safety heartbeat remain on the
Pixel even if all semantic inference moves.

## Why not move the LLM immediately

The standard S100 has 12 GB LPDDR5 and an 80-TOPS BPU. D-Robotics' TogetherROS
2.4.4 release notes explicitly list S100/S100P support for
`DeepSeek_R1_Distill_Qwen_1.5B` and `DeepSeek_R1_Distill_Qwen_7B`. That proves a
supported local-model path exists, but it does not establish PawGuide's
first-token latency, structured-output reliability, sustained temperature or
mobile power draw.

DeepSeek-R1-Distill is also a reasoning-oriented family. Long reasoning traces
can be actively unhelpful in a push-to-talk robot loop. A short instruct model
that reliably emits the PawGuide JSON schema may produce the better demo even
if the larger model has stronger benchmark scores.

## Physical benchmark gate

Benchmark the Pixel model and the two officially supported S100 candidates with
the same 50–100 recorded tour commands. Measure:

| Metric | MVP gate |
|---|---|
| valid strict-schema output | 100% after one bounded retry |
| unsafe or unknown destination | always rejected locally |
| median transcript-to-command latency | <= 700 ms |
| p95 transcript-to-command latency | <= 1.5 s |
| time to first spoken response | <= 1.5 s |
| 30-minute thermal soak | no throttling or service restart |
| simultaneous navigation + inference | no missed 500 ms operator heartbeat |
| mobile supply | no undervoltage, reboot or Pixel discharge |

Run the language benchmark while DimOS, Wi-Fi, Pixel USB tethering and the fan
are active. Test both the standard conversation path and an adversarial set:
unknown waypoints, prompt injection, requests to clear STOP, malformed output
and very long questions.

Record model name, quantization, context length, RDK OS version, TogetherROS
version, power mode, temperature sensors, latency percentiles and maximum RSS.
Do not select a backend from an unloaded desktop benchmark.

## Selection rule

Use the smallest backend that passes the gate:

1. Keep the Pixel backend if it is faster or more reliable.
2. Move command proposal and tour dialogue to the S100 if a local S100 model
   passes without degrading navigation or the safety channel.
3. Use the S100 as primary and Pixel as fallback only after backend switching
   has been tested with the robot stationary.
4. Do not run two models in an uncontrolled race; use one active backend with a
   visible health state and a bounded fallback.

The 7B model is a candidate, not the automatic choice. On the 12 GB S100,
memory headroom must include DimOS, mapping, the gateway, model runtime and
kernel buffers.

## BPU perception track

The current RDK S model-zoo branch requires RDK OS 4.0.5 or newer and uses the
board-provided `hbm_runtime` Python API with `.hbm` models. Perception is the
best first use of the BPU:

- person detection for social distance and safe stopping;
- body/pose or gesture recognition;
- banner/sign recognition for tour context;
- later, visual-language context.

Perception output remains advisory until calibrated. It may request a stop, but
it may not release one.

## Deferred board commands

Do not download multi-gigabyte models into the release bundle before the S100
is present. After flashing and passing `check-s100-readiness.sh`, confirm the
installed RDK/TogetherROS versions, then follow the matching official example
for that release. Model files belong on the 64 GB eMMC or an M.2 Key-M SSD, not
on Hetzner and not in Git.

Official references:

- <https://d-robotics.github.io/rdk_doc/en/Robot_development/quick_start/changelog/>
- <https://d-robotics.github.io/rdk_s_doc/en/Algorithm_Application/model_zoo_intro/>
- <https://d-robotics.github.io/rdk_s_doc/en/Algorithm_Application/python-api/>
- <https://d-robotics.github.io/rdk_doc/en/rdk_s/Algorithm_Application/model_zoo/rdk_s_guide/>
