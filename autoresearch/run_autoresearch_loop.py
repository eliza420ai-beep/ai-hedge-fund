"""
Autoresearch loop: edit params → evaluate → commit/revert.
Runs one sector at a time. Uses simple heuristic tweaks (no LLM).
Schedule via cron for overnight runs.

Usage:
    poetry run python -m autoresearch.run_autoresearch_loop --sector equipment --iterations 5
    poetry run python -m autoresearch.run_autoresearch_loop --sector equipment --dry-run
"""

import argparse
import importlib
import json
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from statistics import median
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
LOGS_DIR = PROJECT_ROOT / "autoresearch" / "logs"

# Default technical indicators to tweak for sector params (e.g. equipment, tech).
TWEAKABLE = [
    ("RSI_OVERSOLD", 25, 35, 1),
    ("RSI_OVERBOUGHT", 65, 80, 1),
    ("RSI_LOOKBACK", 12, 18, 1),
    ("EMA_SHORT", 3, 10, 1),
    ("EMA_MEDIUM", 15, 30, 1),
    ("EMA_LONG", 40, 60, 1),
]

# Sleeve-specific knobs: only factor/tier-related parameters, not core technicals.
SLEEVE_TWEAKABLE = {
    # Tastytrade AI infra sleeve (params_tastytrade_sleeve.py)
    "tastytrade_sleeve": [
        ("MIN_VALUE_SCORE", 0.0, 0.6, 0.05),
        ("MIN_QUALITY_SCORE", 0.0, 0.6, 0.05),
        ("INSIDER_NET_SELL_THRESHOLD", -0.2, 0.2, 0.05),
        ("INSIDER_SIZE_MULTIPLIER", 0.4, 1.0, 0.05),
    ],
    # Hyperliquid HIP-3 equity sleeve (params_hl_hip3_sleeve.py)
    "hl_hip3_sleeve": [
        ("MIN_VALUE_SCORE", 0.0, 0.6, 0.05),
        ("MIN_QUALITY_SCORE", 0.0, 0.6, 0.05),
        ("INSIDER_NET_SELL_THRESHOLD", -0.2, 0.2, 0.05),
        ("INSIDER_SIZE_MULTIPLIER", 0.4, 1.0, 0.05),
    ],
}


def get_param_value(mod, name: str):
    return getattr(mod, name, None)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_loop_event(sector: str, event: dict) -> None:
    """Append structured loop events for postmortems and auditability."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOGS_DIR / f"autoresearch_loop_{sector}.jsonl"
    payload = {"ts": _iso_now(), **event}
    with open(path, "a") as f:
        f.write(json.dumps(payload, default=str) + "\n")


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path,
    sector: str,
    stage: str,
    check: bool = False,
    capture_output: bool = True,
) -> subprocess.CompletedProcess:
    """Run command and optionally fail fast with structured logs."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=capture_output, text=True)
    if result.returncode != 0:
        append_loop_event(
            sector,
            {
                "event": "command_failed",
                "stage": stage,
                "cmd": cmd,
                "returncode": result.returncode,
                "stdout_tail": "\n".join(result.stdout.splitlines()[-20:]),
                "stderr_tail": "\n".join(result.stderr.splitlines()[-20:]),
            },
        )
        if check:
            raise RuntimeError(f"Command failed at stage={stage}: {' '.join(cmd)}")
    return result


def format_value_like(original, candidate):
    """Preserve int/float semantics when writing params values."""
    if isinstance(original, int):
        return str(int(round(candidate)))
    if isinstance(original, float):
        return repr(float(candidate))
    return repr(candidate)


def set_param_in_file(path: Path, name: str, value) -> bool:
    content = path.read_text()
    lines = content.splitlines()
    out = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{name} ") or line.strip().startswith(f"{name}="):
            out.append(f"{name} = {value}")
            found = True
        else:
            out.append(line)
    if not found:
        return False
    path.write_text("\n".join(out) + "\n")
    return True


def restore_param_file(params_path: Path, sector: str) -> bool:
    rel = params_path.relative_to(PROJECT_ROOT)
    result = run_cmd(
        ["git", "restore", "--source=HEAD", "--worktree", "--", str(rel)],
        cwd=PROJECT_ROOT,
        sector=sector,
        stage="restore_params",
        check=False,
    )
    return result.returncode == 0


def parse_val_sharpe(stdout: str) -> float | None:
    """Parse only the canonical metric line: val_sharpe=<float>."""
    pattern = re.compile(r"^val_sharpe=([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)$")
    for line in stdout.splitlines():
        m = pattern.match(line.strip())
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def parse_val_max_dd(stdout: str) -> float | None:
    """Parse val_max_dd=<float> (signed, e.g. -17.67). Used for 'trust max_dd' check."""
    pattern = re.compile(r"^val_max_dd=([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)$")
    for line in stdout.splitlines():
        m = pattern.match(line.strip())
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def run_eval(sector: str, oos: bool = False) -> tuple[float | None, float | None, subprocess.CompletedProcess, int]:
    """Return (sharpe, max_dd, proc, elapsed_ms). max_dd is None if parse fails."""
    t0 = time.time()
    cmd = ["poetry", "run", "python", "-m", "autoresearch.evaluate", "--params", f"autoresearch.params_{sector}"]
    if oos:
        cmd.extend(["--start", "2025-08-01", "--end", "2026-03-07"])
    result = run_cmd(cmd, cwd=PROJECT_ROOT, sector=sector, stage="eval", check=False)
    elapsed_ms = int((time.time() - t0) * 1000)
    if result.returncode != 0:
        return None, None, result, elapsed_ms
    return parse_val_sharpe(result.stdout), parse_val_max_dd(result.stdout), result, elapsed_ms


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sector", type=str, required=True, help="Sector name (e.g. equipment, memory)")
    parser.add_argument("--iterations", type=int, default=10, help="Max iterations per run")
    parser.add_argument("--dry-run", action="store_true", help="Only run eval, no edits/commits")
    parser.add_argument("--oos", action="store_true", help="Use OOS window for eval")
    parser.add_argument("--confirm-runs", type=int, default=1, help="Repeat eval N times and use median score")
    parser.add_argument("--min-delta", type=float, default=1e-6, help="Minimum Sharpe improvement to accept")
    parser.add_argument(
        "--require-oos-improvement",
        action="store_true",
        help="When using in-sample eval, also require OOS Sharpe to improve before keep",
    )
    parser.add_argument(
        "--require-max-dd-no-worse",
        action="store_true",
        default=True,
        help="Reject candidate if in-sample max drawdown worsened (default: True; see CAVEATS.md)",
    )
    parser.add_argument(
        "--no-require-max-dd-no-worse",
        action="store_false",
        dest="require_max_dd_no_worse",
        help="Disable reject-when-max-dd-worsens check",
    )
    parser.add_argument(
        "--max-dd-tolerance",
        type=float,
        default=1.0,
        help="Reject if candidate max_dd < best - tolerance (percentage points; default 1.0)",
    )
    args = parser.parse_args()

    sector = args.sector
    params_path = PROJECT_ROOT / "autoresearch" / f"params_{sector}.py"
    results_path = PROJECT_ROOT / "autoresearch" / f"results_{sector}.tsv"
    if not params_path.exists():
        print(f"Params not found: {params_path}")
        return 1

    if args.confirm_runs < 1:
        print("--confirm-runs must be >= 1")
        return 1

    tweakables = SLEEVE_TWEAKABLE.get(sector, TWEAKABLE)

    baseline, baseline_max_dd, baseline_proc, baseline_elapsed = run_eval(sector, oos=args.oos)
    if baseline is None:
        print("Baseline eval failed.")
        append_loop_event(
            sector,
            {
                "event": "baseline_failed",
                "oos": args.oos,
                "elapsed_ms": baseline_elapsed,
                "stdout_tail": "\n".join(baseline_proc.stdout.splitlines()[-20:]),
                "stderr_tail": "\n".join(baseline_proc.stderr.splitlines()[-20:]),
            },
        )
        return 1
    print(f"Baseline Sharpe: {baseline:.4f}")
    if baseline_max_dd is not None:
        print(f"Baseline max DD: {baseline_max_dd:.2f}%")
    append_loop_event(
        sector,
        {
            "event": "baseline",
            "oos": args.oos,
            "sharpe": baseline,
            "max_dd": baseline_max_dd,
            "elapsed_ms": baseline_elapsed,
        },
    )

    if args.dry_run:
        return 0

    best = baseline
    best_max_dd = baseline_max_dd  # more negative = worse
    best_oos = None
    if args.require_oos_improvement and not args.oos:
        base_oos, _, _, _ = run_eval(sector, oos=True)
        if base_oos is None:
            print("OOS baseline eval failed; cannot enforce --require-oos-improvement")
            return 1
        best_oos = base_oos
        print(f"Baseline OOS Sharpe: {best_oos:.4f}")

    for i in range(args.iterations):
        mod = importlib.reload(importlib.import_module(f"autoresearch.params_{sector}"))
        tweak = random.choice(tweakables)
        name, lo, hi, step = tweak
        val = get_param_value(mod, name)
        if val is None:
            continue
        delta = random.choice([-step, step])
        new_val = max(lo, min(hi, val + delta))
        if new_val == val:
            continue
        if not set_param_in_file(params_path, name, format_value_like(val, new_val)):
            continue

        run_scores: list[float] = []
        last_proc = None
        elapsed_total_ms = 0
        for _ in range(args.confirm_runs):
            sharpe, _, proc, elapsed_ms = run_eval(sector, oos=args.oos)
            last_proc = proc
            elapsed_total_ms += elapsed_ms
            if sharpe is None:
                break
            run_scores.append(sharpe)

        if len(run_scores) != args.confirm_runs:
            restore_ok = restore_param_file(params_path, sector)
            append_loop_event(
                sector,
                {
                    "event": "eval_failed_reverted",
                    "iter": i + 1,
                    "param": name,
                    "old_value": val,
                    "new_value": new_val,
                    "restore_ok": restore_ok,
                    "elapsed_total_ms": elapsed_total_ms,
                    "stdout_tail": "\n".join((last_proc.stdout if last_proc else "").splitlines()[-20:]),
                    "stderr_tail": "\n".join((last_proc.stderr if last_proc else "").splitlines()[-20:]),
                },
            )
            if not restore_ok:
                print("CRITICAL: failed to restore params after eval failure. Aborting.")
                return 2
            continue

        sharpe_med = float(median(run_scores))
        accepted = sharpe_med > (best + args.min_delta)

        candidate_oos = None
        if accepted and args.require_oos_improvement and not args.oos:
            candidate_oos, _, proc_oos, oos_elapsed_ms = run_eval(sector, oos=True)
            elapsed_total_ms += oos_elapsed_ms
            if candidate_oos is None:
                accepted = False
                append_loop_event(
                    sector,
                    {
                        "event": "oos_eval_failed",
                        "iter": i + 1,
                        "param": name,
                        "old_value": val,
                        "new_value": new_val,
                        "stdout_tail": "\n".join(proc_oos.stdout.splitlines()[-20:]),
                        "stderr_tail": "\n".join(proc_oos.stderr.splitlines()[-20:]),
                    },
                )
            elif best_oos is not None and candidate_oos <= (best_oos + args.min_delta):
                accepted = False

        # Trust max_dd: reject if drawdown worsened (more negative) beyond tolerance
        if accepted and args.require_max_dd_no_worse and best_max_dd is not None and last_proc is not None:
            candidate_max_dd = parse_val_max_dd(last_proc.stdout)
            if candidate_max_dd is not None and candidate_max_dd < best_max_dd - args.max_dd_tolerance:
                accepted = False
                append_loop_event(
                    sector,
                    {
                        "event": "rejected_max_dd_worse",
                        "iter": i + 1,
                        "param": name,
                        "old_value": val,
                        "new_value": new_val,
                        "median_score": sharpe_med,
                        "candidate_max_dd": candidate_max_dd,
                        "best_max_dd": best_max_dd,
                        "tolerance": args.max_dd_tolerance,
                    },
                )

        if accepted:
            try:
                best = sharpe_med
                if candidate_oos is not None:
                    best_oos = candidate_oos
                if last_proc is not None:
                    cand_dd = parse_val_max_dd(last_proc.stdout)
                    if cand_dd is not None:
                        best_max_dd = cand_dd
                rel_params = params_path.relative_to(PROJECT_ROOT)
                rel_results = results_path.relative_to(PROJECT_ROOT)
                run_cmd(
                    ["git", "add", str(rel_params), str(rel_results)],
                    cwd=PROJECT_ROOT,
                    sector=sector,
                    stage="git_add",
                    check=True,
                )
                run_cmd(
                    ["git", "commit", "-m", f"autoresearch[{sector}]: {name}={format_value_like(val, new_val)} sharpe={sharpe_med:.4f}"],
                    cwd=PROJECT_ROOT,
                    sector=sector,
                    stage="git_commit",
                    check=True,
                )
            except RuntimeError:
                restore_ok = restore_param_file(params_path, sector)
                print("CRITICAL: git failure while keeping candidate; params restored, aborting.")
                append_loop_event(
                    sector,
                    {
                        "event": "git_failure_abort",
                        "iter": i + 1,
                        "param": name,
                        "old_value": val,
                        "new_value": new_val,
                        "restore_ok": restore_ok,
                    },
                )
                return 2
            print(f"  Commit: {name}={format_value_like(val, new_val)} sharpe={sharpe_med:.4f}")
            append_loop_event(
                sector,
                {
                    "event": "accepted",
                    "iter": i + 1,
                    "param": name,
                    "old_value": val,
                    "new_value": new_val,
                    "scores": run_scores,
                    "median_score": sharpe_med,
                    "best": best,
                    "candidate_oos": candidate_oos,
                    "best_oos": best_oos,
                    "elapsed_total_ms": elapsed_total_ms,
                },
            )
        else:
            restore_ok = restore_param_file(params_path, sector)
            if not restore_ok:
                print("CRITICAL: failed to restore params after rejected candidate. Aborting.")
                return 2
            append_loop_event(
                sector,
                {
                    "event": "rejected",
                    "iter": i + 1,
                    "param": name,
                    "old_value": val,
                    "new_value": new_val,
                    "scores": run_scores,
                    "median_score": sharpe_med,
                    "best": best,
                    "candidate_oos": candidate_oos,
                    "best_oos": best_oos,
                    "elapsed_total_ms": elapsed_total_ms,
                },
            )
    print(f"Best Sharpe: {best:.4f}")
    if best_max_dd is not None:
        print(f"Best max DD: {best_max_dd:.2f}%")
    append_loop_event(
        sector,
        {
            "event": "loop_complete",
            "iterations": args.iterations,
            "best": best,
            "best_max_dd": best_max_dd,
            "best_oos": best_oos,
            "confirm_runs": args.confirm_runs,
            "min_delta": args.min_delta,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
