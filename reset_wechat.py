"""Reset WeChat credentials and restart channel."""

import asyncio
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from thumbelina.channels.wechat_qrcode import _accounts_dir


def reset_credentials():
    """Delete all saved WeChat credentials."""

    accounts_dir = _accounts_dir()
    print(f"Accounts directory: {accounts_dir}")

    if not accounts_dir.exists():
        print("No accounts directory found - nothing to reset")
        return

    cred_files = list(accounts_dir.glob("*.json"))
    if not cred_files:
        print("No credential files found - nothing to reset")
        return

    print(f"\nFound {len(cred_files)} credential file(s):")
    for f in cred_files:
        print(f"  - {f.name}")

    print("\nDeleting all credential files...")
    for f in cred_files:
        try:
            f.unlink()
            print(f"  ✓ Deleted {f.name}")
        except Exception as e:
            print(f"  ✗ Failed to delete {f.name}: {e}")

    print("\n✅ All credentials deleted!")
    print("\nNext steps:")
    print("  1. Restart thumbelina server")
    print("  2. Scan new QR code via /api/v1/wechat/qrcode")
    print("  3. Confirm login via /api/v1/wechat/qrcode/confirm")


if __name__ == "__main__":
    reset_credentials()
