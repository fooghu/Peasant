"""
Ramses DLMM Range Monitor
--------------------------
Checks whether a DLMM position's bin range still contains the pool's
active bin, and sends a Telegram alert when the position falls
out of range (or comes back in range).

Run this on a schedule (cron, Task Scheduler, or GitHub Actions —
see README.md for both setups).
"""

import os
import sys
import urllib.request
import urllib.parse
from web3 import Web3

# ---- Configuration ----------------------------------------------------
# Fill these in via environment variables (recommended) or edit directly.

RPC_URL = os.environ.get("RPC_URL", "https://rpc.mainnet.chain.robinhood.com")
POOL_ADDRESS = os.environ.get("POOL_ADDRESS", "0xc5ce1f3aae5744271e228256a0bead5f4ab1cbe0")
MIN_BIN_ID = int(os.environ.get("MIN_BIN_ID", "8383438"))
MAX_BIN_ID = int(os.environ.get("MAX_BIN_ID", "8383445"))
POSITION_LABEL = os.environ.get("POSITION_LABEL", "FRONG/WETH DLMM")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ---- Contract interface ------------------------------------------------
# Minimal ABI fragment — just the one read function we need.
#
# ASSUMPTION: Ramses DLMM bin IDs are centered on 2^23 (8,388,608), matching
# the Trader Joe Liquidity Book (LBPair) scheme, so this uses the standard
# LBPair "getActiveId()" call. VERIFY this before relying on it:
#   1. Open your pool address on robinhoodchain.blockscout.com
#   2. Go to Contract -> Read Contract
#   3. Confirm "getActiveId" exists and returns a number close to your
#      active bin (8383438 in your case). If it's named differently,
#      swap the "name" fields below to match.

LBPAIR_ABI = [
    {
        "inputs": [],
        "name": "getActiveId",
        "outputs": [{"internalType": "uint24", "name": "", "type": "uint24"}],
        "stateMutability": "view",
        "type": "function",
    }
]

STATE_FILE = "last_state.txt"  # tracks in/out-of-range status between runs


def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[warn] Telegram not configured — printing message instead:")
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode(
        {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    ).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception as e:
        print(f"[error] Failed to send Telegram alert: {e}")


def read_last_state() -> str:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return f.read().strip()
    return "unknown"


def write_last_state(state: str) -> None:
    with open(STATE_FILE, "w") as f:
        f.write(state)


def main():
    if POOL_ADDRESS.startswith("0xPASTE"):
        print("[error] Set POOL_ADDRESS to your actual pool contract address.")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        print(f"[error] Could not connect to RPC at {RPC_URL}")
        sys.exit(1)

    pool = w3.eth.contract(
        address=Web3.to_checksum_address(POOL_ADDRESS), abi=LBPAIR_ABI
    )

    try:
        active_id = pool.functions.getActiveId().call()
    except Exception as e:
        print(
            "[error] getActiveId() call failed — the pool may use a "
            "different function name than assumed. Check the contract's "
            f"Read tab on the block explorer. Details: {e}"
        )
        sys.exit(1)

    in_range = MIN_BIN_ID <= active_id <= MAX_BIN_ID
    current_state = "in_range" if in_range else "out_of_range"
    last_state = read_last_state()

    print(
        f"Active bin: {active_id} | Your range: {MIN_BIN_ID}-{MAX_BIN_ID} | "
        f"{'IN RANGE' if in_range else 'OUT OF RANGE'}"
    )

    # Only alert on a state CHANGE when running somewhere state persists
    # (local cron / VPS). On ephemeral runners like GitHub Actions, state
    # resets each run, so you'll get a fresh alert every run while out of
    # range — see README for why that's actually fine there.
    if current_state != last_state:
        if not in_range:
            direction = "above" if active_id > MAX_BIN_ID else "below"
            send_telegram(
                f"🚨 {POSITION_LABEL} is OUT OF RANGE.\n"
                f"Active bin {active_id} has moved {direction} your range "
                f"({MIN_BIN_ID}-{MAX_BIN_ID}). Position has stopped earning fees."
            )
        else:
            send_telegram(
                f"✅ {POSITION_LABEL} is back IN RANGE (active bin {active_id})."
            )
        write_last_state(current_state)


if __name__ == "__main__":
    main()
