"""Document why interactive B2C sign-in from a dev machine doesn't work.

This was originally going to drive `msal.PublicClientApplication.acquire_token_interactive`
to seed a refresh_token for the B2C_1A_signin policy. That doesn't work: Kohler's
B2C app registration only has two redirect URIs whitelisted:

  * `msauth://com.kohler.hermoth/2DuDM2vGmcL4bKPn2xKzKpsy68k%3D` (Android app)
  * `oauth-redirect.googleusercontent.com/r/kohlerkonnect-prodtest` (Google Home)

Neither matches `http://localhost:<port>` (MSAL's default for interactive
flows), and B2C tenants don't publish a device-code endpoint either. So
there's no headless or browser-on-dev-machine path that completes.

**Use the AVD MITM capture instead:**

    cd credential-extraction
    make harness                              # boots AVD, patched APK installed
    # In the emulator, manually sign in to Konnect using your real credentials.
    # mitmproxy intercepts the OAuth POST and dumps the refresh_token to a file.

After capture, the refresh_token is written to:
    ~/Library/Caches/kohler-anthem/token-captures/<ts>/refresh_token.txt

Add it to your env (the path token_capture.py prints points to <ts>/refresh_token.txt):

    export KOHLER_B2C_REFRESH_TOKEN=$(cat <path-from-token_capture-output>)

The library uses silent refresh from then on — re-running this is only needed
if Kohler revokes the refresh_token (rare; the Android app survives months
without re-signing-in).
"""

from __future__ import annotations

import sys


def main() -> int:
    sys.stderr.write(__doc__ + "\n")
    sys.stderr.write("\nThis helper is deprecated. Use the AVD MITM path above.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
