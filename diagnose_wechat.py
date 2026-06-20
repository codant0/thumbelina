"""Diagnose WeChat iLink connection issues."""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add project to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from thumbelina.channels.wechat_qrcode import ILinkClient, _accounts_dir, _normalize_id


async def diagnose():
    """Run diagnostics on WeChat iLink connection."""

    print("=" * 60)
    print("WeChat iLink Connection Diagnostics")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Try to load saved credentials
    accounts_dir = _accounts_dir()
    print(f"\n1. Checking accounts directory: {accounts_dir}")

    if not accounts_dir.exists():
        print("❌ No accounts directory found")
        print("   → Need to scan QR code to authenticate")
        return

    cred_files = list(accounts_dir.glob("*.json"))
    if not cred_files:
        print("❌ No credential files found")
        print("   → Need to scan QR code to authenticate")
        return

    print(f"✅ Found {len(cred_files)} credential file(s)")

    for cred_file in cred_files:
        print(f"\n{'=' * 60}")
        print(f"2. Checking credential file: {cred_file.name}")
        print(f"{'=' * 60}")

        import json
        data = json.loads(cred_file.read_text(encoding="utf-8"))

        bot_token = data.get("bot_token", "")
        ilink_bot_id = data.get("ilink_bot_id", "")
        ilink_user_id = data.get("ilink_user_id", "")
        base_url = data.get("baseurl", "https://ilinkai.weixin.qq.com")

        print(f"Bot ID: {ilink_bot_id[:30]}..." if len(ilink_bot_id) > 30 else f"Bot ID: {ilink_bot_id}")
        print(f"Bot Token: {'***' + bot_token[-6:] if bot_token else '(empty)'}")
        print(f"User ID: {ilink_user_id[:20]}..." if len(ilink_user_id) > 20 else f"User ID: {ilink_user_id}")
        print(f"Base URL: {base_url}")

        if not bot_token:
            print("\n❌ No bot token - need to re-authenticate")
            continue

        if not ilink_bot_id:
            print("\n❌ No bot ID - credentials may be corrupted")
            continue

        # Try to connect
        print(f"\n3. Testing iLink connection...")
        client = ILinkClient(
            bot_token=bot_token,
            ilink_bot_id=ilink_bot_id,
            ilink_user_id=ilink_user_id,
            base_url=base_url,
        )

        print(f"   UIN (base64): {client._uin}")
        print(f"   Headers: {json.dumps(client._headers(), indent=2)}")

        try:
            # Try a quick getupdates (with short timeout)
            print(f"\n4. Calling getupdates (10s timeout)...")
            messages, sync_buffer = await asyncio.wait_for(
                client.getupdates(sync_buffer=""),
                timeout=10.0
            )
            print(f"\n✅ Connection successful!")
            print(f"   Received {len(messages)} message(s)")
            print(f"   Sync buffer length: {len(sync_buffer)}")

            if messages:
                print("\n   Recent messages:")
                for msg in messages[:3]:
                    from thumbelina.channels.wechat_qrcode import extract_text
                    text = extract_text(msg)
                    print(f"   - From {msg.from_user_id}: {text[:50]}...")

        except asyncio.TimeoutError:
            print(f"\n⚠️  Connection timeout (10s)")
            print("   Possible causes:")
            print("   - iLink API is slow or unreachable")
            print("   - Network issues")
            print("   - Firewall blocking connection")
        except Exception as e:
            print(f"\n❌ Connection failed: {type(e).__name__}: {e}")

            # Check for specific error codes
            if hasattr(e, 'response'):
                try:
                    resp_data = e.response.json()
                    errcode = resp_data.get("errcode", 0)
                    errmsg = resp_data.get("errmsg", "")

                    print(f"\n   iLink API Response:")
                    print(f"   - Error code: {errcode}")
                    print(f"   - Error message: {errmsg}")

                    if errcode == -14:
                        print(f"\n   → DIAGNOSIS: Session expired!")
                        print(f"   → The bot_token is no longer valid")
                        print(f"   → Need to re-scan QR code to get new credentials")
                    elif errcode == -1:
                        print(f"\n   → DIAGNOSIS: System error")
                        print(f"   → iLink API may be experiencing issues")
                    elif errcode != 0:
                        print(f"\n   → DIAGNOSIS: Unknown error code {errcode}")
                except Exception as parse_err:
                    print(f"   (Could not parse response: {parse_err})")
            else:
                print(f"\n   No response object available")

        finally:
            await client.close()

    print(f"\n{'=' * 60}")
    print("5. Recommendations")
    print(f"{'=' * 60}")
    print("If you see 'Session expired' (errcode=-14):")
    print("  1. Clear old credentials: rm ~/.weclaw/accounts/*.json")
    print("  2. Restart thumbelina server")
    print("  3. Scan new QR code via /api/v1/wechat/qrcode")
    print("  4. Confirm login via /api/v1/wechat/qrcode/confirm")


if __name__ == "__main__":
    asyncio.run(diagnose())
