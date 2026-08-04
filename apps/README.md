# Ichiban apps — Apple TV board + iPad screens

Two native apps for the five Apple devices in the restaurant. Both are internal
builds signed with your own developer account; neither goes near the App Store.

| Target | Device | What it is |
|---|---|---|
| `IchibanBoard` | Apple TV | **Native.** tvOS has no WebKit at all — no Safari, no `WKWebView` — so the guest board is written in SwiftUI against the public `/api/display/<id>` feed. |
| `IchibanScreens` | 4 × iPad | **Native shell around the web pages.** iOS does have WebKit, so each screen is the page the server already renders. A menu change or bug fix reaches every iPad on the next load — no rebuild, no re-signing, no review. |

## Build

```bash
cd apps
./generate.sh              # writes Ichiban.xcodeproj from project.yml
open Ichiban.xcodeproj
```

`generate.sh` reads `APPLE_TEAM_ID` from `../.env` and sets the signing team on
both targets, so a regenerated project is ready to run instead of needing the
team picked by hand twice. Find the ID at
developer.apple.com → Membership (a 10-character string like `A1B2C3D4E5`).

The tvOS target needs the tvOS platform installed once:

```bash
xcodebuild -downloadPlatform tvOS      # ~5 GB
```

## Installing on the real Apple TV

1. Apple TV: Settings → Remotes and Devices → **Remote App and Devices** (leave
   this screen open — it listens for the pairing request)
2. Xcode: Window → Devices and Simulators → the Apple TV appears → **Pair**,
   type the code shown on the TV
3. Both on the same wifi as the Mac
4. Select `IchibanBoard` + your Apple TV, Run
5. First launch: press **Play/Pause** on the remote, enter the server address

Same for the iPads with `IchibanScreens`, over USB or wifi.

## Setting up a device

Neither app is hardcoded to a server. On first launch each one asks for the
server address and restaurant ID, and stores them on the device. Moving the
server to the VPS, or replacing a dead Mac mini, is a settings change on five
devices — never a rebuild and re-sign of five apps.

- **iPad:** first launch shows a picker — Kiosk, Sushi bar, Hot line, Reception,
  or Pay. Choose once. Three fingers held on the screen for 1.5 s returns to it.
- **Apple TV:** the board starts immediately. Press **Play/Pause** on the remote
  to open setup.

## Signing, and the date you must not forget

Development builds signed with a paid developer account stop launching after
**one year**. Put a calendar reminder on it — otherwise the board and the kitchen
screens fail on a random Tuesday, mid-service.

The iPads have a fallback if that happens: open the same URLs in Safari and use
"Add to Home Screen". The Apple TV has none — which is why the Raspberry Pi
option in `DEPLOY.md` §7b is still worth keeping as a spare.

## Why the iPads are a web shell and not native SwiftUI

Four screens that all show live server state, on the same wifi as the server.
Rewriting them natively would buy push notifications and offline caching, and
cost a rebuild-and-reinstall cycle on four devices for every menu tweak. The
shell adds the two things Safari doesn't: the screen never sleeps, and it
reloads on wake, so an iPad that slept through a server restart comes back
showing live orders instead of an error page nobody notices.

## Zettle card reader (kiosk self-payment)

The app is credential-ready. To activate the reader:

1. **developer.zettle.com** → create an app for the iOS Payments SDK with:
   - Bundle ID: `se.ichiban.screens`
   - OAuth redirect URI: `ichiban://zettle` (must match exactly — the app
     declares this URL scheme)
2. In Xcode: File → Add Package Dependencies → `https://github.com/iZettle/sdk-ios`
   (the `ZettleSDKDriver` behind `#if canImport(iZettleSDK)` activates by itself;
   its charge call may need a one-line signature touch-up against the SDK version)
3. On the kiosk iPad: three-finger hold → settings → paste the **Zettle client ID**
   → relaunch → tap **Log in to Zettle** once with the restaurant's account
4. Pair the Zettle Reader 2 over Bluetooth (the SDK's settings UI handles it)

From then on, "pay by card here" at the kiosk drives the reader with the
server-computed amount, and a successful tap settles the order automatically.

⚠️ Do not go live with this lane before Zettle confirms in writing that
SDK-initiated sales fall under their certified kassaregister — otherwise the
kiosk may legally count as our own register, which requires a certified
kontrollsystem. Until then the counter flow stays compliant.
