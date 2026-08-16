"""
Ramses DLMM Range Monitor - Desktop GUI
-----------------------------------------
Paste your pool address (or the full Ramses app URL), set your bin
range and check interval, click Start. It keeps checking in the
background for as long as this window stays open, logs every check,
and (optionally) pings Telegram when your range status changes.

Requires: pip install web3
(tkinter ships with the standard python.org Windows installer already)
"""

import json
import os
import re
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import urllib.request
import urllib.parse

from web3 import Web3

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_config.json")
DEFAULT_RPC = "https://rpc.mainnet.chain.robinhood.com"

# Known position from our earlier chat -- used only as a first-run default,
# your saved config.json takes over after that.
DEFAULT_POOL = "0xc5ce1f3aae5744271e228256a0bead5f4ab1cbe0"
DEFAULT_MIN_BIN = "8383438"
DEFAULT_MAX_BIN = "8383445"

LBPAIR_ABI = [
    {
        "inputs": [],
        "name": "getActiveId",
        "outputs": [{"internalType": "uint24", "name": "", "type": "uint24"}],
        "stateMutability": "view",
        "type": "function",
    }
]

ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")


def extract_address(text):
    """Pull a contract address out of either a raw address or a full
    Ramses app URL like .../manage/0xabc...123?chainId=4663"""
    match = ADDRESS_RE.search(text.strip())
    return match.group(0) if match else None


class MonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Ramses DLMM Range Monitor")
        self.root.geometry("580x540")
        self.running = False
        self.thread = None
        self.last_state = "unknown"

        self.build_ui()
        self.load_config()

    # ---------- UI ----------
    def build_ui(self):
        pad = {"padx": 10, "pady": 4}

        frame = ttk.Frame(self.root)
        frame.pack(fill="x", **pad)

        ttk.Label(frame, text="Pool address or Ramses URL:").grid(row=0, column=0, sticky="w")
        self.pool_entry = ttk.Entry(frame, width=60)
        self.pool_entry.grid(row=1, column=0, columnspan=2, sticky="we", pady=(0, 8))

        ttk.Label(frame, text="Min bin ID:").grid(row=2, column=0, sticky="w")
        self.min_bin_entry = ttk.Entry(frame, width=20)
        self.min_bin_entry.grid(row=3, column=0, sticky="w")

        ttk.Label(frame, text="Max bin ID:").grid(row=2, column=1, sticky="w")
        self.max_bin_entry = ttk.Entry(frame, width=20)
        self.max_bin_entry.grid(row=3, column=1, sticky="w")

        ttk.Label(frame, text="Check every:").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.interval_var = tk.StringVar(value="5 minutes")
        interval_menu = ttk.Combobox(
            frame, textvariable=self.interval_var, state="readonly", width=18,
            values=["3 minutes", "5 minutes", "10 minutes", "15 minutes"],
        )
        interval_menu.grid(row=5, column=0, sticky="w")

        ttk.Label(frame, text="RPC URL (advanced, optional):").grid(row=4, column=1, sticky="w", pady=(8, 0))
        self.rpc_entry = ttk.Entry(frame, width=30)
        self.rpc_entry.insert(0, DEFAULT_RPC)
        self.rpc_entry.grid(row=5, column=1, sticky="w")

        tg_frame = ttk.LabelFrame(
            self.root, text="Telegram alerts (optional -- leave blank to just watch this window)"
        )
        tg_frame.pack(fill="x", **pad)

        ttk.Label(tg_frame, text="Bot token:").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.token_entry = ttk.Entry(tg_frame, width=42, show="*")
        self.token_entry.grid(row=0, column=1, sticky="w", padx=8)

        ttk.Label(tg_frame, text="Chat ID:").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.chat_entry = ttk.Entry(tg_frame, width=42)
        self.chat_entry.grid(row=1, column=1, sticky="w", padx=8)

        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", **pad)

        self.start_btn = ttk.Button(btn_frame, text="Start Monitoring", command=self.toggle_monitoring)
        self.start_btn.pack(side="left")

        self.status_label = ttk.Label(btn_frame, text="Stopped", foreground="gray")
        self.status_label.pack(side="left", padx=12)

        ttk.Label(self.root, text="Log:").pack(anchor="w", padx=10)
        self.log_box = scrolledtext.ScrolledText(self.root, height=16, state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- Config persistence ----------
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                self.pool_entry.insert(0, cfg.get("pool", DEFAULT_POOL))
                self.min_bin_entry.insert(0, cfg.get("min_bin", DEFAULT_MIN_BIN))
                self.max_bin_entry.insert(0, cfg.get("max_bin", DEFAULT_MAX_BIN))
                self.interval_var.set(cfg.get("interval", "5 minutes"))
                if cfg.get("rpc"):
                    self.rpc_entry.delete(0, tk.END)
                    self.rpc_entry.insert(0, cfg["rpc"])
                self.token_entry.insert(0, cfg.get("token", ""))
                self.chat_entry.insert(0, cfg.get("chat", ""))
                return
            except Exception:
                pass  # fall through to defaults if config is corrupt
        # First run, no saved config yet -- prefill with the known position
        self.pool_entry.insert(0, DEFAULT_POOL)
        self.min_bin_entry.insert(0, DEFAULT_MIN_BIN)
        self.max_bin_entry.insert(0, DEFAULT_MAX_BIN)

    def save_config(self):
        cfg = {
            "pool": self.pool_entry.get().strip(),
            "min_bin": self.min_bin_entry.get().strip(),
            "max_bin": self.max_bin_entry.get().strip(),
            "interval": self.interval_var.get(),
            "rpc": self.rpc_entry.get().strip(),
            "token": self.token_entry.get().strip(),
            "chat": self.chat_entry.get().strip(),
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)

    # ---------- Logging (thread-safe) ----------
    def log(self, message):
        def _write():
            self.log_box.configure(state="normal")
            timestamp = time.strftime("%H:%M:%S")
            self.log_box.insert("end", f"[{timestamp}] {message}\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.root.after(0, _write)

    # ---------- Telegram ----------
    def send_telegram(self, message):
        token = self.token_entry.get().strip()
        chat_id = self.chat_entry.get().strip()
        if not token or not chat_id:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
        except Exception as e:
            self.log(f"Telegram send failed: {e}")

    # ---------- Monitoring control ----------
    def toggle_monitoring(self):
        if self.running:
            self.running = False
            self.start_btn.configure(text="Start Monitoring")
            self.status_label.configure(text="Stopped", foreground="gray")
            self.log("Monitoring stopped.")
            return

        pool_input = self.pool_entry.get().strip()
        address = extract_address(pool_input)
        if not address:
            messagebox.showerror("Missing pool address", "Paste a valid pool address or Ramses URL first.")
            return

        try:
            min_bin = int(self.min_bin_entry.get().strip())
            max_bin = int(self.max_bin_entry.get().strip())
        except ValueError:
            messagebox.showerror("Invalid bin range", "Min/Max bin ID must be whole numbers.")
            return

        self.save_config()
        self.running = True
        self.last_state = "unknown"
        self.start_btn.configure(text="Stop Monitoring")
        self.status_label.configure(text="Running...", foreground="green")
        self.log(f"Started monitoring {address} (range {min_bin}-{max_bin}).")

        interval_map = {"3 minutes": 180, "5 minutes": 300, "10 minutes": 600, "15 minutes": 900}
        interval_sec = interval_map.get(self.interval_var.get(), 300)

        self.thread = threading.Thread(
            target=self.monitor_loop, args=(address, min_bin, max_bin, interval_sec), daemon=True
        )
        self.thread.start()

    def monitor_loop(self, address, min_bin, max_bin, interval_sec):
        rpc_url = self.rpc_entry.get().strip() or DEFAULT_RPC
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            pool = w3.eth.contract(address=Web3.to_checksum_address(address), abi=LBPAIR_ABI)
        except Exception as e:
            self.log(f"Could not set up connection: {e}")
            return

        while self.running:
            try:
                active_id = pool.functions.getActiveId().call()
                in_range = min_bin <= active_id <= max_bin
                state = "in_range" if in_range else "out_of_range"
                self.log(
                    f"Active bin: {active_id} | Range: {min_bin}-{max_bin} | "
                    f"{'IN RANGE' if in_range else 'OUT OF RANGE'}"
                )
                if state != self.last_state:
                    if not in_range:
                        direction = "above" if active_id > max_bin else "below"
                        self.send_telegram(
                            f"Position OUT OF RANGE. Active bin {active_id} moved "
                            f"{direction} your range ({min_bin}-{max_bin})."
                        )
                    else:
                        self.send_telegram(f"Position back IN RANGE (active bin {active_id}).")
                    self.last_state = state
            except Exception as e:
                self.log(f"Check failed: {e}")

            # Sleep in 1-second ticks so the Stop button reacts immediately
            for _ in range(interval_sec):
                if not self.running:
                    break
                time.sleep(1)

    def on_close(self):
        self.running = False
        self.save_config()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MonitorApp(root)
    root.mainloop()
