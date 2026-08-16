# Ramses DLMM Range Monitor

Checks your DLMM position's active bin against your deposited range and
pings you on Telegram when it goes out of range.

## Easiest option: the desktop app (monitor_gui.py)

No terminal commands after setup — paste, click, watch.

1. Open a terminal in this folder once, and run:
   ```
   pip install -r requirements.txt
   python monitor_gui.py
   ```
2. A window opens with the pool address and bin range already filled in
   (your FRONG/WETH position). Paste a different pool address or the
   full Ramses URL if you want to monitor something else — it extracts
   the address either way.
3. Pick how often to check (3/5/10/15 minutes) from the dropdown.
4. (Optional) Fill in Telegram bot token + chat ID if you want phone
   alerts — see the Telegram setup steps below. Leave blank to just
   watch the log in the window.
5. Click **Start Monitoring**. It checks on your chosen interval and
   logs every result live. Click **Stop Monitoring** to pause.

**Important limitation:** this only runs while the window is open and
your computer is on. Closing it stops the checks. If you want
monitoring that keeps running even when your PC is off, use the
GitHub Actions option further down instead — same underlying logic,
runs in the cloud.

Your settings are saved to `gui_config.json` next to the script, so
next time you open the app they're already filled in.

---

## Command-line / always-on options

The steps below are for `monitor.py`, the plain script version — use
these if you want it running unattended in the cloud (GitHub Actions)
or don't want a GUI.

## 1. Get a Telegram bot token (2 minutes, free)

1. Open Telegram, message **@BotFather**, send `/newbot`, follow the
   prompts. It gives you a **bot token** like `123456:ABC-def...`.
2. Message your new bot anything (e.g. "hi") so it can message you back.
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
   — find `"chat":{"id":123456789` in the response. That number is your
   **chat ID**.

## 2. Fill in your values

- `POOL_ADDRESS` — the full FRONG/WETH pool address (your screenshot showed
  it truncated as `0xc5ce..cbe0` — grab the full address from the app or
  Blockscout).
- `MIN_BIN_ID` / `MAX_BIN_ID` — `8383438` / `8383445` from your position
  (update these if you redeploy with a new range).
- `RPC_URL` — defaults to the public Robinhood Chain RPC
  (`https://rpc.mainnet.chain.robinhood.com`). Fine for this use case
  (one read call every few minutes).

## 3. Verify the contract call once, before trusting this long-term

Open your pool address on `robinhoodchain.blockscout.com` → **Contract** →
**Read Contract** → confirm a function called `getActiveId` exists and
returns something close to `8383438`. If Ramses named it differently,
edit the `"name"` fields in `monitor.py`'s `LBPAIR_ABI`.

## 4. Run it — pick one

### Option A: GitHub Actions (free, no server, easiest)

1. Push this folder to a new **private** GitHub repo.
2. Repo → Settings → Secrets and variables → Actions → add secrets:
   `POOL_ADDRESS`, `MIN_BIN_ID`, `MAX_BIN_ID`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID` (and `RPC_URL` only if you want a different one).
3. It runs automatically every 10 minutes.
4. Note: GitHub's runners are ephemeral, so the "only alert once per
   state change" logic resets each run — meaning you'll get an alert
   **every 10 minutes while out of range**, not just once. Treat that as
   a nag reminder until you rebalance, not a bug.

### Option B: Run locally / on your own machine or VPS (one alert per change)

```bash
pip install -r requirements.txt
export POOL_ADDRESS="0x..."
export MIN_BIN_ID="8383438"
export MAX_BIN_ID="8383445"
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
python monitor.py
```

Then schedule it:
- **Mac/Linux:** `crontab -e`, add `*/10 * * * * cd /path/to/dlmm-monitor && python monitor.py`
- **Windows:** Task Scheduler, run every 10 minutes.

Here, `last_state.txt` persists between runs, so you get exactly one
alert when you go out of range, and one when you come back in — no spam.

## Updating after you redeploy a new range

Every time you recenter your ladder (as discussed — recentering at ~60%
clearance), update `MIN_BIN_ID` / `MAX_BIN_ID` to match the new range.
This script only knows the range you tell it.
