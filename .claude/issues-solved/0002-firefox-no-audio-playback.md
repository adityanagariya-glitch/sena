---
id: 0002
symptom: "Firefox plays no audio from Gemini Live (Chrome works)"
aliases:
  - "no sound in Firefox"
  - "Firefox silent playback"
  - "createBuffer NotSupportedError"
  - "sample rate mismatch audio context"
  - "browser-specific audio bug Gemini"
root_cause: "Separate AudioContext instances for mic capture and playback; Firefox rejects cross-context buffer operations at non-matching sample rates"
tags: [gemini-live, audio, firefox, browser]
files: [sena-ai/demo_client.html]
fix_commit: "df27ba4"
date_solved: 2026-04-17
verified: "Firefox playback confirmed on demo client, multi-turn"
---

# 0002 — Firefox no audio playback

## Symptom

On Firefox: connection succeeds, model transcripts arrive, but no sound plays. Chrome plays fine with same code. No console error initially; sometimes `createBuffer` throws `NotSupportedError` at sample rate mismatch.

## Root cause

Two `AudioContext` instances were created — one for mic capture (at native rate, typically 48kHz), one for playback (forced to 24kHz to match Gemini output). Firefox strictly enforces per-context sample rates and refuses to route 24kHz buffers through a 48kHz context chain. Chrome silently resamples; Firefox does not.

## Fix

**Use a single AudioContext. Manually upsample 24kHz Gemini audio to the context's native rate before `createBuffer`.**

```diff
- this.micCtx = new AudioContext();
- this.playCtx = new AudioContext({ sampleRate: 24000 });
+ this.audioCtx = new AudioContext();  // single context, native rate

  // playback
- const buf = this.playCtx.createBuffer(1, pcm.length, 24000);
+ const upsampled = upsamplePCM(pcm, 24000, this.audioCtx.sampleRate);
+ const buf = this.audioCtx.createBuffer(1, upsampled.length, this.audioCtx.sampleRate);
  buf.getChannelData(0).set(upsampled);
```

Upsample function (linear interpolation is sufficient for speech):

```js
function upsamplePCM(input, fromRate, toRate) {
  const ratio = toRate / fromRate;
  const out = new Float32Array(Math.floor(input.length * ratio));
  for (let i = 0; i < out.length; i++) {
    const src = i / ratio;
    const lo = Math.floor(src), hi = Math.min(lo + 1, input.length - 1);
    out[i] = input[lo] + (input[hi] - input[lo]) * (src - lo);
  }
  return out;
}
```

See commit `df27ba4` for full diff.

## Failed attempts (do NOT retry)

- **`OfflineAudioContext` for resampling** — adds latency, breaks streaming playback
- **Forcing AudioContext sample rate via constructor option** — Firefox ignores the option on some versions
- **`<audio>` tag + MediaSource** — PCM buffers aren't supported without MSE encoding overhead
- **Two separate contexts with manual ScriptProcessor bridging** — cross-context audio routing is not reliable in Firefox
- **Trusting Chrome behavior** — Chrome silently resamples cross-rate, Firefox does not; testing only Chrome hides this class of bug

## Why this fix (not alternatives)

Single-context + manual upsample is the minimum viable path that works in both browsers with low latency. Linear interpolation is good enough for speech (saves us FFT-based resampler weight).

## Related

- Wiki: [[gemini-live-multi-turn-config]]
- Memory: `feedback_gemini_live_patterns.md` rule 4+5
