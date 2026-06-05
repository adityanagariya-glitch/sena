# Flutter Diagnostic — Voice Onboarding Bootstrap Payload

> **For:** Flutter dev on `sena-mobile` repo.
> **Goal:** Capture the existing `VoiceCtrl` diagnostic logs to confirm what `bootstrap.current_page_values` we send to the AI backend on session create.
> **No code changes needed.** Logging already exists at `voice_session_controller.dart:425-456`. Just need to read it.

---

## Why we need this

Backend reports that after `POST /v1/onboarding/session` the agent re-asks for fields the user already filled (address, emergency contact). Cross-screen context is intentionally off-limits. The remaining suspect is per-screen state:

- `bootstrap.current_page_values` carries pre-filled UI values into the session.
- If it arrives empty or wrong-shape, agent falls back to `next_required_field()` → walks schema top-down → re-asks everything.

We need to see what Flutter is **actually** sending in that field for a session where the bug reproduces.

---

## Where the logs are

File: `lib/features/voice_onboarding/presentation/controllers/voice_session_controller.dart`

Lines 425-456 already emit, on every session create:

```
VoiceCtrl: ── sink.readMappableValues() (N total) ──
VoiceCtrl:   FILLED  fullName → basics.full_name = Aditya Nagariya
VoiceCtrl:   EMPTY   address  (no value)
VoiceCtrl:   UNMAPPED (3): [foo, bar, baz]
VoiceCtrl: ── currentPageValues sent to backend: N filled fields ──
VoiceCtrl: currentPageValues { "basics.full_name": "...", ... }
```

The block prints right BEFORE the POST to `/v1/onboarding/session`. Logs use `AppLogger.debug` / `AppLogger.json` with tag `VoiceCtrl`.

---

## How to capture — pick one

### Option A — `flutter logs` (fastest, terminal-only)

```powershell
# In sena-mobile repo root
cd C:\Users\Admin\Downloads\sena-mobile\sena-mobile
flutter devices     # confirm device/emulator connected
flutter logs | Select-String -Pattern "VoiceCtrl"
```

Then trigger voice in the running app. Lines appear in terminal.

### Option B — `flutter run` (installs fresh debug build + tails logs)

```powershell
cd C:\Users\Admin\Downloads\sena-mobile\sena-mobile
flutter run
```

Watch terminal. To filter noise, use a second terminal with the `Select-String` command above.

### Option C — Android Studio Logcat (GUI)

1. Open project in Android Studio
2. Bottom panel → **Logcat** tab
3. Device dropdown → pick yours
4. Filter box → type `VoiceCtrl`
5. Trigger voice in app → logs appear

### Option D — VS Code Debug Console

1. Run app via VS Code `Run > Start Debugging` (or F5)
2. Debug Console tab shows all `AppLogger` output
3. Use Ctrl+F to search for `VoiceCtrl`

---

## Reproduction steps

1. Fresh launch of app (kill + restart).
2. Sign in.
3. Open Personal Information onboarding step.
4. Wait for fields to pre-fill (name, email, phone — whatever the API returns).
5. Tap the voice / orb button → triggers `POST /v1/onboarding/session`.
6. **Capture all `VoiceCtrl` lines between this tap and the next `agent_said` event.**

If the bug reproduces only after a "new session" tap (not first-time), include the logs from BOTH session creates so we can diff.

---

## What to send back

Paste the full `VoiceCtrl` block in Slack / issue tracker. Specifically these lines:

- `── sink.readMappableValues() (N total) ──` ← the `N` matters
- Every `FILLED  ... → ... = ...` line
- Every `EMPTY  ...` line
- The `UNMAPPED (N): [...]` line if present
- `── currentPageValues sent to backend: N filled fields ──`
- The final `currentPageValues { ... }` JSON

PII reminder: emails/phones in the JSON are real participant data. Share only via private/encrypted channel, not public chat.

---

## What each pattern tells us (so you can self-diagnose)

| Log shows | Diagnosis | Owner |
|-----------|-----------|-------|
| `sink.readMappableValues() (0 total)` | Step screen never called `_sink.bind(...)` for its fields | Flutter |
| `UNMAPPED (N): [...]` with N high | `voicePath.fromController(key)` returns `null` for most keys — mapping table missing entries | Flutter |
| `EMPTY` for fields visibly filled in UI | Race: bootstrap built before `TextEditingController`s populated from API response | Flutter |
| `currentPageValues: 0 filled fields` + UI shows data | `_sink` not wired to the active step controller | Flutter |
| `currentPageValues: N filled fields` (matches UI) | Flutter is correct → backend issue | AI backend team |

If the last row matches your output, paste the JSON anyway and ping AI backend — we'll trace from the matching backend log (`debug_client_bootstrap_payload`, already deployed-pending on next push).

---

## Quick sanity-check command

If you just want the COUNT without the full dump:

```powershell
flutter logs | Select-String -Pattern "currentPageValues sent to backend"
```

One line per session-create. If you see `0 filled fields` — that's the bug confirmed without needing the JSON.

---

## Common gotchas

- **`flutter` not on PATH** → `where.exe flutter`. If empty, add `<flutter-sdk>\bin` to PATH or use full path `C:\src\flutter\bin\flutter.bat`.
- **No device listed** → check USB cable, enable Developer Options + USB Debugging on Android; trust this computer on iOS.
- **Logs flood with non-Flutter stuff** → use `Select-String -Pattern "VoiceCtrl"` to filter.
- **App installed from Play Store / TestFlight** → `flutter logs` won't see it. Either rebuild with `flutter run` or use `adb logcat | findstr VoiceCtrl` directly.

---

*Last updated: 2026-05-18 — paired with `routes.py` `debug_client_bootstrap_payload` log on the backend side.*
