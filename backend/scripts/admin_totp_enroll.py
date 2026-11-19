"""One-time local enrollment: generate an admin-console TOTP secret.

Not part of the running app — run once locally to generate a fresh secret,
scan the printed QR code into an authenticator app (Google Authenticator,
1Password, Authy, ...), then set the printed secret as ADMIN_TOTP_SECRET in
the Render dashboard (see render.yaml). There are no backup codes — losing
the authenticator means rotating ADMIN_TOTP_SECRET.

Run from backend/ with the venv active:
    python scripts/admin_totp_enroll.py
    python scripts/admin_totp_enroll.py --account admin@example.com
"""

import argparse
import sys
from pathlib import Path

# backend/ must be on sys.path so `from app.*` resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pyotp
import qrcode  # type: ignore[import-untyped]

# Matches the FastAPI app title / product name —
# not worth a shared constant for a script that runs once per admin enrolled.
ISSUER_NAME = "Event Radar Admin"
DEFAULT_ACCOUNT_NAME = "admin"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--account",
        default=DEFAULT_ACCOUNT_NAME,
        help="Label shown under the entry in the authenticator app (default: %(default)s)",
    )
    args = parser.parse_args()

    secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=args.account, issuer_name=ISSUER_NAME
    )

    print(f"ADMIN_TOTP_SECRET={secret}\n")
    print("Scan this QR code, then set the secret above as ADMIN_TOTP_SECRET")
    print("in the Render dashboard (backend service env vars):\n")
    qr = qrcode.QRCode()
    qr.add_data(uri)
    qr.print_ascii(invert=True)
    print(f"\nIf your app can't scan a terminal QR code, enter this URI manually:\n{uri}")


if __name__ == "__main__":
    main()
