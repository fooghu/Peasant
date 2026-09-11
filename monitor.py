"""
Ramses Multi-Position Monitor
-------------------------------
Watches any number of DLMM or CL positions, across any number of
chains, defined in config.json. Sends Telegram alerts on range status
changes, responds to on-demand commands, and writes docs/data.json
for the web dashboard (docs/index.html).

Telegram commands:
  /status              -- status of every configured position
  /status <name>        -- status of one position, e.g. /status FRONG/WETH
  /logfee <name> <amt>  -- log a fee amount for one position
  /history <name>       -- last 5 logged fee entries + total for one position
  /list                 -- list configured position names

Run this on a schedule (cron, Task Scheduler, or GitHub Actions).
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
from web3 import Web3

CONFIG_FILE = "config.json"
STATE_FILE = "state.json"
FEE_LOG_FILE = "fee_log.json"
DASHBOARD_FILE = os.path.join("docs", "data.json")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MAX_HISTORY = 100

DLMM_ABI = [
    {
        "inputs": [],
        "name": "getActiveId",
        "outputs": [{"internalType": "uint24", "name": "", "type": "uint24"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# Standard Uniswap-V3-style pool interface -- Ramses CL is built on
# Uniswap V3's core contracts, so this is the standard call, not a guess
# the way getActiveId() initially was.
CL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]


# ---- Small JSON helpers -----------------------------------------------

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, data):
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---- Telegram -----------------------------------------------------------

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[warn] Telegram not configured — printing instead:")
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": message}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception as e:
        print(f"[error] Telegram send failed: {e}")


def fetch_telegram_updates():
    if not TELEGRAM_BOT_TOKEN:
        return []
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?timeout=0"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[warn] Could not fetch Telegram updates: {e}")
        return []
    updates = data.get("result", [])
    if not updates:
        return []
    last_id = max(u["update_id"] for u in updates)
    ack_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={last_id + 1}"
    try:
        urllib.request.urlopen(ack_url, timeout=10)
    except Exception as e:
        print(f"[warn] Could not acknowledge Telegram updates: {e}")
    return updates


# ---- Position checking ----------------------------------------------

def classify(value, low, high, warning_fraction):
    """Returns 'out_of_range', 'warning', or 'safe'. Works for bin IDs
    or ticks -- both are just integers, ticks can be negative, the
    arithmetic doesn't care."""
    if value < low or value > high:
        return "out_of_range"
    width = high - low
    if width == 0:
        return "warning"
    frac = (value - low) / width
    if frac >= warning_fraction or frac <= (1 - warning_fraction):
        return "warning"
    return "safe"


_web3_cache = {}


def get_web3(chain_name, chain_cfg):
    if chain_name not in _web3_cache:
        _web3_cache[chain_name] = Web3(Web3.HTTPProvider(chain_cfg["rpc_url"]))
    return _web3_cache[chain_name]


def check_position(pos, chains):
    chain_cfg = chains[pos["chain"]]
    w3 = get_web3(pos["chain"], chain_cfg)
    if not w3.is_connected():
        raise RuntimeError(f"Could not connect to {pos['chain']} RPC")

    address = Web3.to_checksum_address(pos["pool_address"])

    if pos["type"] == "dlmm":
        contract = w3.eth.contract(address=address, abi=DLMM_ABI)
        value = contract.functions.getActiveId().call()
        low, high = pos["min_bin"], pos["max_bin"]
    elif pos["type"] == "cl":
        contract = w3.eth.contract(address=address, abi=CL_ABI)
        slot0 = contract.functions.slot0().call()
        value = slot0[1]  # tick
        low, high = pos["tick_lower"], pos["tick_upper"]
    else:
        raise ValueError(f"Unknown position type: {pos['type']}")

    warning_fraction = pos.get("early_warning_fraction", 0.7)
    state = classify(value, low, high, warning_fraction)
    return value, low, high, state


# ---- Telegram commands ---------------------------------------------

def handle_status_command(positions, results, name_filter=None):
    lines = []
    for pos in positions:
        if name_filter and pos["name"].lower() != name_filter.lower():
            continue
        r = results.get(pos["name"])
        if not r:
            continue
        lines.append(
            f"{pos['name']} ({pos['chain']}/{pos['type']}): "
            f"{r['value']} in [{r['low']}, {r['high']}] — {r['state'].upper()}"
        )
    if not lines:
        return "No matching position found." if name_filter else "No positions configured."
    return "\n".join(lines)


def handle_commands(positions, results, fee_logs):
    updates = fetch_telegram_updates()
    if not updates:
        return

    for u in reversed(updates):
        text = u.get("message", {}).get("text", "").strip()
        if not text:
            continue
        parts = text.split()
        cmd = parts[0].lower()

        if cmd == "/status":
            name_filter = parts[1] if len(parts) > 1 else None
            send_telegram(handle_status_command(positions, results, name_filter))
            return

        if cmd == "/logfee":
            if len(parts) >= 3:
                name, amount_str = parts[1], parts[2]
                try:
                    amount = float(amount_str)
                    fee_logs.setdefault(name, []).append(
                        {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "amount": amount}
                    )
                    send_telegram(f"Logged {amount} in fees for {name}.")
                except ValueError:
                    send_telegram("Use: /logfee <position name> <amount>, e.g. /logfee FRONG/WETH 5.25")
            else:
                send_telegram("Use: /logfee <position name> <amount>, e.g. /logfee FRONG/WETH 5.25")
            return

        if cmd == "/history":
            if len(parts) >= 2:
                name = parts[1]
                entries = fee_logs.get(name, [])
                if not entries:
                    send_telegram(f"No fee entries logged yet for {name}.")
                else:
                    recent = entries[-5:]
                    lines = [f"{e['timestamp']}: {e['amount']}" for e in recent]
                    total = sum(e["amount"] for e in entries)
                    send_telegram(
                        f"{name} — last entries:\n" + "\n".join(lines) + f"\n\nTotal: {total:.2f}"
                    )
            else:
                send_telegram("Use: /history <position name>")
            return

        if cmd == "/list":
            names = ", ".join(p["name"] for p in positions) or "none configured"
            send_telegram(f"Configured positions: {names}")
            return


# ---- Main ---------------------------------------------------------------

def main():
    config = load_json(CONFIG_FILE, None)
    if config is None:
        print(f"[error] {CONFIG_FILE} not found. See README for the format.")
        sys.exit(1)

    chains = config.get("chains", {})
    positions = config.get("positions", [])

    state = load_json(STATE_FILE, {"positions": {}})
    fee_logs = load_json(FEE_LOG_FILE, {})
    dashboard = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "positions": [],
    }

    results = {}

    for pos in positions:
        name = pos["name"]
        pos_state = state["positions"].setdefault(name, {"last_state": "unknown", "history": []})

        try:
            value, low, high, current_state = check_position(pos, chains)
        except Exception as e:
            print(f"[error] {name}: {e}")
            continue

        results[name] = {"value": value, "low": low, "high": high, "state": current_state}
        print(f"{name}: value={value} range=[{low},{high}] state={current_state.upper()}")

        last_state = pos_state["last_state"]
        if current_state != last_state:
            if current_state == "out_of_range":
                direction = "above" if value > high else "below"
                send_telegram(
                    f"🚨 {name} is OUT OF RANGE.\nCurrent {value} moved {direction} "
                    f"your range ({low}-{high}). Not earning fees."
                )
            elif current_state == "warning":
                send_telegram(
                    f"⚠️ {name} is close to the edge of its range.\n"
                    f"Current {value}, range {low}-{high}. Still in range, worth watching."
                )
            else:
                send_telegram(f"✅ {name} is back in the safe middle of its range (current {value}).")
            pos_state["last_state"] = current_state

        pos_state["history"].append(
            {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "value": value, "state": current_state}
        )
        pos_state["history"] = pos_state["history"][-MAX_HISTORY:]

        dashboard["positions"].append(
            {
                "name": name,
                "chain": pos["chain"],
                "type": pos["type"],
                "value": value,
                "low": low,
                "high": high,
                "state": current_state,
                "history": pos_state["history"],
            }
        )

    save_json(STATE_FILE, state)
    save_json(DASHBOARD_FILE, dashboard)

    handle_commands(positions, results, fee_logs)
    save_json(FEE_LOG_FILE, fee_logs)  # in case a /logfee command added an entry


if __name__ == "__main__":
    main()
