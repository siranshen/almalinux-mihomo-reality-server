# Chrome timezone launcher on macOS

## Goal

Create a Dock launcher named **Chrome Los Angeles** that starts the normal
Google Chrome with `TZ=America/Los_Angeles`. Leave the system timezone, Chrome
installation, and Chrome profile configuration unchanged.

This setup is **required for this project's macOS Chrome workflow**, alongside
[proxy/client setup](client-setup.md). It changes Chrome's timezone, not its IP
address, geolocation, or language, and is not WebRTC leak protection.

## Setup checklist

These instructions can be given to an AI agent. Inspect the Mac first and adapt
the implementation rather than assuming a particular macOS version or Dock
layout.

1. **Check prerequisites.** Confirm `/Applications/Google Chrome.app` exists;
   otherwise stop and ask the user. Check that `/usr/bin/open` supports `--env`;
   if not, stop and discuss alternatives. Inspect any existing launcher before
   changing it.
2. **Create the launcher** at `~/Applications/Chrome Los Angeles.app`, with
   standard `Contents/MacOS` and `Contents/Resources` directories. Create an
   executable `Contents/MacOS/chrome-launcher` containing:

   ```sh
   #!/bin/sh
   exec /usr/bin/open --env TZ=America/Los_Angeles -a "/Applications/Google Chrome.app"
   ```

   Add a valid `Contents/Info.plist` with bundle name/display name
   `Chrome Los Angeles`, identifier `local.chrome-los-angeles.launcher`,
   executable `chrome-launcher`, package type `APPL`, and icon `app.icns`.
   Copy Chrome's icon from its app resources into the launcher's resources;
   inspect the installed app if the expected `app.icns` is missing. Validate
   the plist and script, then refresh the launcher's icon cache as needed.
3. **Add it to the Dock**, without duplicates or changes to unrelated entries.
   If automatic pinning does not work, ask the user to drag the app from
   `~/Applications` into the Dock. Ask before removing the pinned normal Chrome
   icon; unpinning must not remove Chrome itself.
4. **Test a fresh start.** With the user's permission, quit Chrome normally
   (`Cmd+Q`) and wait until it fully exits; do not force-kill it. Open the
   launcher from the Dock. An agent may use macOS `open` to test launching, but
   should distinguish this from visually checking the Dock. Confirm the system
   timezone is unchanged, then ask the user to open Chrome DevTools
   (`Cmd+Option+J`) and run:

   ```js
   Intl.DateTimeFormat().resolvedOptions().timeZone
   ```

   Expected result: `"America/Los_Angeles"`. A process-level check of `TZ` is
   useful, but does not replace this browser check.

Do not modify Chrome's app bundle or profile settings, create a separate Chrome
profile, or change the system timezone to achieve this.

## Everyday use and caveats

- **Timezone is applied only when Chrome starts.** If Chrome is already
  running, the launcher brings it forward without changing its timezone. Fully
  quit Chrome and start it again using **Chrome Los Angeles**.
- If Chrome is closed and a link in another app starts it normally, the LA
  timezone is not applied. Quit Chrome and relaunch using the launcher.
- **Chrome's normal icon still appears in the Dock while Chrome is running, even
  if it was unpinned. This is expected.** The launcher starts the real Chrome;
  it is not a separate browser.
- If an update changes Chrome's icon, recopy the icon into the launcher and
  refresh it. Do not modify the original Chrome app.
