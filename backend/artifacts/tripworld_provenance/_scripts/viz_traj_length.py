"""Trajectory length distribution for Trip World.

A *trajectory* is one trail_id — a single session of consecutive check-ins.
Each travel-behavior row in travel_behaviors.parquet bundles many trails
(median ~12 hometown trails + ~2 OOT trails per τ record), so to get
honest trajectory lengths we explode c_h and c_o by trail_id and count
check-ins per trail.

Output:  viz/trajectory_length.pdf
Run:     python _scripts/viz_traj_length.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
OUT_DIR = ROOT / "viz"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def trail_lengths(arrays):
    """Walk a column of c_h / c_o object arrays and emit the per-trail
    check-in counts, **deduplicated globally by trail_id**.

    The same hometown trail typically appears inside many τ records (one
    per distinct destination the same user travels to). We count each
    trail's length once. Within a single τ record, all check-ins sharing a
    trail_id together form that trail."""
    trail_to_len = {}
    cur = {}
    for lst in arrays:
        cur.clear()
        for ck in lst:
            tid = ck["trail_id"]
            cur[tid] = cur.get(tid, 0) + 1
        for tid, n in cur.items():
            trail_to_len[tid] = n
    return np.fromiter(trail_to_len.values(), dtype=np.int64, count=len(trail_to_len))


def main():
    print("[load] travel_behaviors  (c_h, c_o) — exploding by trail_id")
    tb = pd.read_parquet(ROOT / "travel_behaviors.parquet",
                         columns=["c_h", "c_o"])
    print(f"  τ records: {len(tb):,}")
    h = trail_lengths(tb["c_h"].values)
    o = trail_lengths(tb["c_o"].values)
    print(f"  hometown trails: {len(h):,}  median={int(np.median(h))}  mean={h.mean():.2f}  "
          f"p10={int(np.percentile(h,10))}  p90={int(np.percentile(h,90))}  max={h.max()}")
    print(f"  OOT      trails: {len(o):,}  median={int(np.median(o))}  mean={o.mean():.2f}  "
          f"p10={int(np.percentile(o,10))}  p90={int(np.percentile(o,90))}  max={o.max()}")

    HOME = "#1f77b4"
    TRIP = "#d62728"
    home_label = f"Hometown trajectories  (n={len(h):,}, median {int(np.median(h))})"
    trip_label = f"OOT trajectories  (n={len(o):,}, median {int(np.median(o))})"

    fig, ax = plt.subplots(figsize=(7, 4.2))

    # Integer-length, side-by-side bars. Lengths 1..CAP get their own
    # bar pair; everything past CAP is folded into a single ">CAP" pair.
    CAP = 10
    lengths = np.arange(1, CAP + 1)
    h_counts = np.array([(h == L).sum() for L in lengths] + [(h > CAP).sum()])
    o_counts = np.array([(o == L).sum() for L in lengths] + [(o > CAP).sum()])

    x = np.arange(len(h_counts))
    width = 0.4
    ax.bar(x - width / 2, h_counts, width, color=HOME, label=home_label)
    ax.bar(x + width / 2, o_counts, width, color=TRIP, label=trip_label)
    ax.set_xticks(x)
    ax.set_xticklabels([str(L) for L in lengths] + [f">{CAP}"])

    ax.set_xlabel("Number of check-ins")
    ax.set_ylabel("Number of trajectories")
    ax.set_title("Trajectory length distribution")
    ax.legend()
    fig.tight_layout()

    print(f"  > {CAP} check-ins:  hometown {(h > CAP).sum():,} / {len(h):,} "
          f"({(h > CAP).mean()*100:.2f}%);  "
          f"oot {(o > CAP).sum():,} / {len(o):,} "
          f"({(o > CAP).mean()*100:.2f}%)")
    out = OUT_DIR / "trajectory_length.pdf"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)

    # Drop the older versions if they're around, so only one canonical file remains.
    for old_name in ("trajectory_length_per_tau.pdf",
                     "trajectory_length_per_trip.pdf",
                     "trajectory_length_per_trajectory.pdf"):
        old = OUT_DIR / old_name
        if old.exists():
            old.unlink()
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
