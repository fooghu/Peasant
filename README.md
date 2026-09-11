# Ramses Multi-Position Monitor

Watches any number of DLMM or CL positions, on any chain, and gives you:
- Telegram push alerts on range status changes
- On-demand Telegram commands
- A web dashboard you can open from your phone or PC

## What changed from the single-pool version

Everything pool-specific now lives in **config.json** instead of GitHub
secrets. Only your Telegram credentials stay as secrets. This means
adding a new position later is just editing config.json and pushing --
no more juggling POOL_ADDRESS/MIN_BIN_ID secrets per position.

If you're migrating from the old single-pool setup: you can delete the
old POOL_ADDRESS, MIN_BIN_ID, MAX_BIN_ID, and RPC_URL secrets -- they're
no longer read by anything. Keep TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.

## config.json format

```json
{
  "chains": {
    "robinhood": { "rpc_url": "https://rpc.mainnet.chain.robinhood.com", "chain_id": 4663 },
    "hyperevm":  { "rpc_url": "https://rpc.hyperliquid.xyz/evm", "chain_id": 999 }
  },
  "positions": [
    {
      "name": "FRONG/WETH",
      "chain": "robinhood",
      "type": "dlmm",
      "pool_address": "0xc5ce1f3aae5744271e228256a0bead5f4ab1cbe0",
      "min_bin": 8383438,
      "max_bin": 8383445,
      "early_warning_fraction": 0.7
    }
  ]
}
```

**Important:** the FRONG/WETH entry above uses the bin range from when
we first set this up. If you've since removed and redeployed that
position (like we discussed for turning it into a fee-earning range),
update min_bin/max_bin to match the new range before relying on this.

### Adding a DLMM position

Copy this block into the `positions` array:

```json
{
  "name": "TENDIES/USDG",
  "chain": "robinhood",
  "type": "dlmm",
  "pool_address": "PASTE_FULL_POOL_ADDRESS",
  "min_bin": 0,
  "max_bin": 0,
  "early_warning_fraction": 0.7
}
```

Get the pool address and bin range from the position's Analytics tab,
same as we did for FRONG originally.

### Adding a CL position

CL positions use ticks instead of bins, and read from `slot0()`
instead of `getActiveId()`:

```json
{
  "name": "SOME/PAIR",
  "chain": "robinhood",
  "type": "cl",
  "pool_address": "PASTE_FULL_POOL_ADDRESS",
  "tick_lower": 0,
  "tick_upper": 0,
  "early_warning_fraction": 0.7
}
```

Ticks can be negative -- that's normal, the math handles it.

### Adding a new chain

Add an entry under `chains` with its RPC URL and chain ID, then
reference that chain's key name in any position.

## Telegram commands

- `/status` -- status of every configured position
- `/status FRONG/WETH` -- status of just one (use the exact name field)
- `/logfee FRONG/WETH 5.25` -- log a fee amount for one position
- `/history FRONG/WETH` -- last 5 logged entries + total for one position
- `/list` -- list all configured position names

Same 5-minute latency as before -- these are picked up on the next
scheduled run, not instantly.

## The web dashboard

`docs/index.html` reads `docs/data.json` (written by monitor.py each
run) and renders a card per position: a colored range bar showing
where the current bin/tick sits, a status badge, and a small history
strip of recent checks.

### Enabling it (one-time)

1. Repo -> Settings -> Pages.
2. Under "Build and deployment", set Source to "Deploy from a branch".
3. Branch: `main`, folder: `/docs`. Save.
4. After a minute, GitHub shows the live URL (something like
   `https://<username>.github.io/<reponame>/`). Bookmark it on your
   phone's home screen for one-tap access.

This requires the repo to be public (which it already is, for
unlimited Actions minutes) -- the dashboard shows pool addresses and
on-chain price data, nothing sensitive.

## Running it

Same as before: GitHub Actions checks everything every 5 minutes,
commits its own state back, and updates the dashboard automatically.
No changes needed to how you deploy this beyond swapping in these
new files.
