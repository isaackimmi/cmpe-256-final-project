"""Visualizations for the raw Trip World dataset.

Reads the parquet files directly (no derived dataset needed) and writes PDFs
into  $TRIP_WORLD_ROOT/viz/.

Figures
-------
1. city_poi_entropy_hist.pdf       — Shannon entropy of per-POI visit counts within each region (home vs OOT).
2. city_user_entropy_hist.pdf      — entropy of check-ins distributed across users per region.
3. checkins_per_city_top30.pdf     — top-30 regions by # check-ins, home/OOT stacked, with city names.
4. trajectory_length_dist.pdf      — per-user check-in count histogram + CDF, home vs OOT.
5. top_travel_pairs.pdf            — top-30 (home → OOT) pairs by # τ records.
6. entropy_vs_size_scatter.pdf     — entropy vs # check-ins per region.
7. world_poi_density.pdf           — global heatmap of POI density (log color scale).
8. world_city_centroids.pdf        — per-city centroids, marker size ∝ # check-ins.
9. world_travel_flows.pdf          — top-100 home → OOT flows as great-circle arcs.
10. country_distribution.pdf       — # cities and # check-ins per country.

Run:
    python _scripts/viz_clean_raw.py
"""
import math
import pickle
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from matplotlib.colors import LogNorm
import os

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
OUT_DIR = ROOT / "viz"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def shannon(counts):
    counts = np.asarray(counts, dtype=np.float64)
    counts = counts[counts > 0]
    if counts.size == 0:
        return 0.0
    p = counts / counts.sum()
    return float(-(p * np.log2(p)).sum())


def per_group_entropy(df, group_col, count_col):
    """Return (group, total, n_unique, H, H_norm) per group."""
    rows = []
    for g, sub in df.groupby(group_col):
        counts = sub[count_col].values
        H = shannon(counts)
        n_unique = (counts > 0).sum()
        total = int(counts.sum())
        H_uniform = math.log2(n_unique) if n_unique > 1 else 0.0
        H_norm = H / H_uniform if H_uniform > 0 else 0.0
        rows.append((g, total, int(n_unique), H, H_norm))
    return pd.DataFrame(rows, columns=[group_col, "total", "n_unique", "H", "H_norm"])


def add_world_features(ax):
    ax.add_feature(cfeature.LAND.with_scale("110m"), facecolor="#f3f1ec", zorder=0)
    ax.add_feature(cfeature.OCEAN.with_scale("110m"), facecolor="#dfeaf2", zorder=0)
    ax.add_feature(cfeature.COASTLINE.with_scale("110m"), linewidth=0.4, color="#777777", zorder=1)
    ax.add_feature(cfeature.BORDERS.with_scale("110m"), linewidth=0.3, color="#999999", zorder=1)
    ax.set_global()


def main():
    print("[load] travel_behaviors")
    tb = pd.read_parquet(ROOT / "travel_behaviors.parquet")
    print(f"  rows={len(tb):,}, users={tb.user_id.nunique():,}, "
          f"home regions={tb.r_h.nunique():,}, oot regions={tb.r_o.nunique():,}")

    print("[load] pois")
    pois = pd.read_parquet(ROOT / "pois.parquet")[["fsq_place_id", "locality", "n_checkins"]]
    print(f"  rows={len(pois):,}")

    print("[load] metadata_all  (for lat/lon)")
    meta = pd.read_parquet(ROOT / "metadata/metadata_all.parquet",
                           columns=["fsq_place_id", "fsq_latitude", "fsq_longitude"])
    pois = pois.merge(meta, on="fsq_place_id", how="left")
    print(f"  pois with coords: {pois['fsq_latitude'].notna().sum():,} / {len(pois):,}")

    print("[load] region_labels")
    region_labels = pd.read_parquet(ROOT / "region_labels.parquet")
    region_name = dict(zip(region_labels["region_id"], region_labels["city_name"]))
    region_country = dict(zip(region_labels["region_id"], region_labels["country_name"]))

    # ------------------------------------------------------------------
    # Build per-(region, venue) home/OOT visit counters by exploding c_h / c_o.
    # ------------------------------------------------------------------
    print("[derive] expanding c_h / c_o into per-checkin (region, venue, user) frame")
    venue_to_locality = dict(zip(pois["fsq_place_id"], pois["locality"]))

    def explode(df, c_col, r_col):
        # Returns flat DataFrame: user_id, region, venue.
        all_user, all_region, all_venue = [], [], []
        # Faster than apply: iterate rows once.
        for u, r, lst in zip(df["user_id"].values, df[r_col].values, df[c_col].values):
            for ck in lst:
                all_user.append(u)
                all_region.append(r)
                all_venue.append(ck["venue_id"])
        return pd.DataFrame({"user_id": np.asarray(all_user, dtype=np.int64),
                             "region": all_region,
                             "venue": all_venue})

    home_ck = explode(tb, "c_h", "r_h")
    oot_ck = explode(tb, "c_o", "r_o")
    print(f"  home check-ins: {len(home_ck):,}")
    print(f"  oot  check-ins: {len(oot_ck):,}")

    # ------------------------------------------------------------------
    # 1) Per-region POI entropy (home and OOT separately).
    # ------------------------------------------------------------------
    print("[plot] city POI entropy")
    home_poi_counts = (home_ck.groupby(["region", "venue"]).size()
                              .reset_index(name="n"))
    oot_poi_counts = (oot_ck.groupby(["region", "venue"]).size()
                             .reset_index(name="n"))

    home_poi_H = per_group_entropy(home_poi_counts, "region", "n")
    oot_poi_H = per_group_entropy(oot_poi_counts, "region", "n")

    # 2) Per-region user-activity entropy.
    home_user_counts = (home_ck.groupby(["region", "user_id"]).size()
                                .reset_index(name="n"))
    oot_user_counts = (oot_ck.groupby(["region", "user_id"]).size()
                               .reset_index(name="n"))
    home_user_H = per_group_entropy(home_user_counts, "region", "n")
    oot_user_H = per_group_entropy(oot_user_counts, "region", "n")

    # Save CSVs for paper tables.
    for df, name in [(home_poi_H, "home_poi_entropy"),
                     (oot_poi_H, "oot_poi_entropy"),
                     (home_user_H, "home_user_entropy"),
                     (oot_user_H, "oot_user_entropy")]:
        df = df.copy()
        df["city_name"] = df["region"].map(region_name)
        df["country"] = df["region"].map(region_country)
        df.to_csv(OUT_DIR / f"{name}.csv", index=False)

    # ---- Plot 1 ----
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].hist(home_poi_H["H"], bins=40, alpha=0.6, color="#1f77b4",
                 label=f"home (n={len(home_poi_H)})")
    axes[0].hist(oot_poi_H["H"], bins=40, alpha=0.6, color="#d62728",
                 label=f"oot (n={len(oot_poi_H)})")
    axes[0].set_xlabel("Shannon entropy (bits) of POI visit distribution")
    axes[0].set_ylabel("# regions")
    axes[0].set_title("Raw POI entropy")
    axes[0].legend()

    axes[1].hist(home_poi_H["H_norm"], bins=40, alpha=0.6, color="#1f77b4", label="home")
    axes[1].hist(oot_poi_H["H_norm"], bins=40, alpha=0.6, color="#d62728", label="oot")
    axes[1].set_xlabel(r"Normalized entropy  $H/\log_2(n_{POIs})$  $\in [0,1]$")
    axes[1].set_title("Normalized POI entropy")
    axes[1].legend()
    fig.suptitle("Per-region POI visit-distribution entropy", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "city_poi_entropy_hist.pdf", bbox_inches="tight")
    plt.close(fig)

    # ---- Plot 2 ----
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].hist(home_user_H["H"], bins=40, alpha=0.6, color="#2ca02c", label="home")
    axes[0].hist(oot_user_H["H"], bins=40, alpha=0.6, color="#9467bd", label="oot")
    axes[0].set_xlabel("Entropy (bits) of check-ins across users")
    axes[0].set_ylabel("# regions")
    axes[0].set_title("Raw user-activity entropy")
    axes[0].legend()

    axes[1].hist(home_user_H["H_norm"], bins=40, alpha=0.6, color="#2ca02c", label="home")
    axes[1].hist(oot_user_H["H_norm"], bins=40, alpha=0.6, color="#9467bd", label="oot")
    axes[1].set_xlabel(r"Normalized entropy  $H/\log_2(n_{users})$  $\in [0,1]$")
    axes[1].set_title("Normalized user-activity entropy")
    axes[1].legend()
    fig.suptitle("Per-region user-activity entropy (low = power-user dominance)", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "city_user_entropy_hist.pdf", bbox_inches="tight")
    plt.close(fig)

    # ------------------------------------------------------------------
    # 3) Top-30 regions by total check-ins.
    # ------------------------------------------------------------------
    print("[plot] top-30 cities by check-ins")
    home_per_region = home_ck.groupby("region").size().rename("home")
    oot_per_region = oot_ck.groupby("region").size().rename("oot")
    per_region = pd.concat([home_per_region, oot_per_region], axis=1).fillna(0).astype(np.int64)
    per_region["total"] = per_region["home"] + per_region["oot"]
    top30 = per_region.sort_values("total", ascending=False).head(30)
    top30_labels = [f"{region_name.get(r, r)}\n({region_country.get(r, '?')})" for r in top30.index]

    fig, ax = plt.subplots(figsize=(13, 6))
    x = np.arange(len(top30))
    ax.bar(x, top30["home"], color="#1f77b4", label="home check-ins")
    ax.bar(x, top30["oot"], bottom=top30["home"], color="#d62728", label="OOT check-ins")
    ax.set_xticks(x)
    ax.set_xticklabels(top30_labels, rotation=60, ha="right", fontsize=7)
    ax.set_ylabel("# check-ins")
    ax.set_title("Top-30 regions by total check-ins (home + OOT)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "checkins_per_city_top30.pdf", bbox_inches="tight")
    plt.close(fig)

    # ------------------------------------------------------------------
    # 4) Per-user trajectory lengths.
    # ------------------------------------------------------------------
    print("[plot] trajectory lengths")
    user_home = tb.groupby("user_id")["n_home_ci"].sum().values
    user_oot = tb.groupby("user_id")["n_travel_ci"].sum().values

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].hist(np.log10(user_home + 1), bins=60, alpha=0.6, color="#1f77b4", label="home")
    axes[0].hist(np.log10(user_oot + 1), bins=60, alpha=0.6, color="#d62728", label="oot")
    axes[0].set_xlabel(r"$\log_{10}$(# check-ins per user)")
    axes[0].set_ylabel("# users")
    axes[0].set_title("Per-user check-in count distribution")
    axes[0].legend()

    sh = np.sort(user_home)
    so = np.sort(user_oot)
    axes[1].plot(sh, np.arange(1, len(sh) + 1) / len(sh), color="#1f77b4", label="home")
    axes[1].plot(so, np.arange(1, len(so) + 1) / len(so), color="#d62728", label="oot")
    axes[1].set_xscale("log")
    axes[1].set_xlabel("# check-ins per user")
    axes[1].set_ylabel("CDF over users")
    axes[1].set_title("Per-user check-in count CDF")
    axes[1].legend()
    fig.suptitle("How active is each user?", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "trajectory_length_dist.pdf", bbox_inches="tight")
    plt.close(fig)

    # ------------------------------------------------------------------
    # 5) Top travel pairs.
    # ------------------------------------------------------------------
    print("[plot] top travel pairs")
    pair_counts = (tb.groupby(["r_h", "r_o"]).size()
                     .sort_values(ascending=False))
    top_pairs = pair_counts.head(30)
    pair_labels = [f"{region_name.get(h, h)} → {region_name.get(o, o)}"
                   for (h, o) in top_pairs.index]

    fig, ax = plt.subplots(figsize=(11, 7))
    y = np.arange(len(top_pairs))
    ax.barh(y, top_pairs.values, color="#ff7f0e")
    ax.set_yticks(y)
    ax.set_yticklabels(pair_labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("# τ travel-behavior records")
    ax.set_title(f"Top-30 (home → OOT) pairs  (of {len(pair_counts):,} pairs total)")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "top_travel_pairs.pdf", bbox_inches="tight")
    plt.close(fig)

    # ------------------------------------------------------------------
    # 6) Entropy vs city size scatter.
    # ------------------------------------------------------------------
    print("[plot] entropy vs size scatter")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].scatter(home_poi_H["total"], home_poi_H["H_norm"], s=8, alpha=0.4,
                    color="#1f77b4", label="home")
    axes[0].scatter(oot_poi_H["total"], oot_poi_H["H_norm"], s=8, alpha=0.4,
                    color="#d62728", label="oot")
    axes[0].set_xscale("log")
    axes[0].set_xlabel("# check-ins in region")
    axes[0].set_ylabel("Normalized POI entropy")
    axes[0].set_title("POI entropy vs region size")
    axes[0].legend()

    axes[1].scatter(home_user_H["total"], home_user_H["H_norm"], s=8, alpha=0.4,
                    color="#2ca02c", label="home")
    axes[1].scatter(oot_user_H["total"], oot_user_H["H_norm"], s=8, alpha=0.4,
                    color="#9467bd", label="oot")
    axes[1].set_xscale("log")
    axes[1].set_xlabel("# check-ins in region")
    axes[1].set_ylabel("Normalized user-activity entropy")
    axes[1].set_title("User entropy vs region size")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "entropy_vs_size_scatter.pdf", bbox_inches="tight")
    plt.close(fig)

    # ------------------------------------------------------------------
    # 7) World POI density heatmap.
    # ------------------------------------------------------------------
    print("[plot] world POI density")
    poi_coord = pois.dropna(subset=["fsq_latitude", "fsq_longitude"]).copy()
    poi_coord["weight"] = poi_coord["n_checkins"].astype(np.float64)

    fig = plt.figure(figsize=(13, 6.5))
    ax = plt.axes(projection=ccrs.Robinson())
    add_world_features(ax)
    h, xedges, yedges = np.histogram2d(
        poi_coord["fsq_longitude"].values,
        poi_coord["fsq_latitude"].values,
        bins=[np.arange(-180, 181, 1), np.arange(-90, 91, 1)],
        weights=poi_coord["weight"].values,
    )
    h = h.T
    h_masked = np.ma.masked_where(h == 0, h)
    mesh = ax.pcolormesh(
        xedges, yedges, h_masked, cmap="magma_r",
        norm=LogNorm(vmin=1, vmax=h_masked.max()),
        transform=ccrs.PlateCarree(), zorder=2,
    )
    cbar = fig.colorbar(mesh, ax=ax, orientation="horizontal", pad=0.04, shrink=0.7)
    cbar.set_label("Total check-ins per 1° × 1° cell (log scale)")
    ax.set_title(f"Global check-in density  (n_POIs = {len(poi_coord):,}; "
                 f"check-ins = {int(poi_coord['weight'].sum()):,})")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "world_poi_density.pdf", bbox_inches="tight")
    plt.close(fig)

    # ------------------------------------------------------------------
    # 8) City centroids.
    # ------------------------------------------------------------------
    print("[plot] city centroids")
    pc = poi_coord.copy()
    pc["lat_w"] = pc["fsq_latitude"] * pc["weight"]
    pc["lon_w"] = pc["fsq_longitude"] * pc["weight"]
    centroid_agg = pc.groupby("locality").agg(
        lat=("lat_w", "sum"),
        lon=("lon_w", "sum"),
        weight=("weight", "sum"),
    )
    centroid_agg["lat"] = centroid_agg["lat"] / centroid_agg["weight"]
    centroid_agg["lon"] = centroid_agg["lon"] / centroid_agg["weight"]

    home_set = set(per_region.index[per_region["home"] > 0])
    oot_set = set(per_region.index[per_region["oot"] > 0])
    both = home_set & oot_set
    only_home = home_set - oot_set
    only_oot = oot_set - home_set

    rows = []
    for r in centroid_agg.index:
        n_h = int(per_region.loc[r, "home"]) if r in per_region.index else 0
        n_o = int(per_region.loc[r, "oot"]) if r in per_region.index else 0
        if r in both:      kind = "both"
        elif r in only_home: kind = "home only"
        elif r in only_oot:  kind = "oot only"
        else:                continue
        rows.append((r, centroid_agg.loc[r, "lat"], centroid_agg.loc[r, "lon"],
                     n_h + n_o, kind))
    cents = pd.DataFrame(rows, columns=["region", "lat", "lon", "n", "kind"])

    fig = plt.figure(figsize=(13, 6.5))
    ax = plt.axes(projection=ccrs.Robinson())
    add_world_features(ax)
    SIZE_SCALE = 1.5
    sizes = SIZE_SCALE * np.sqrt(cents["n"].values)
    palette = {"both": "#2ca02c", "home only": "#1f77b4", "oot only": "#d62728"}

    # 1. Plot the real data WITHOUT label= so the legend doesn't auto-pick a
    #    representative marker size that differs across kinds.
    for kind, color in palette.items():
        m = cents["kind"] == kind
        ax.scatter(
            cents.loc[m, "lon"], cents.loc[m, "lat"],
            s=sizes[m], c=color, alpha=0.55,
            edgecolor="black", linewidth=0.2,
            transform=ccrs.PlateCarree(), zorder=3,
        )

    # 2. Empty proxy scatters at a fixed marker size for the kind legend so
    #    all three swatches render identically.
    KIND_LEGEND_S = 60
    for kind, color in palette.items():
        n = int((cents["kind"] == kind).sum())
        ax.scatter([], [], s=KIND_LEGEND_S, c=color, alpha=0.55,
                   edgecolor="black", linewidth=0.2,
                   label=f"{kind}  (n={n})",
                   transform=ccrs.PlateCarree())

    # 3. Size-reference proxies (these are intentionally size-varying — they
    #    are the *legend's purpose*, not category swatches).
    for ref_n, lbl in [(500, "500"), (10_000, "10K"), (100_000, "100K")]:
        ax.scatter([], [], s=SIZE_SCALE * np.sqrt(ref_n), c="grey", alpha=0.55,
                   edgecolor="black", linewidth=0.2,
                   label=f"≈ {lbl} check-ins", transform=ccrs.PlateCarree())

    ax.legend(loc="lower left", fontsize=8, frameon=True, ncol=2)
    ax.set_title(f"Region coverage  ({len(cents):,} regions)")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "world_city_centroids.pdf", bbox_inches="tight")
    plt.close(fig)

    # ------------------------------------------------------------------
    # 9) Top-100 travel flows.
    # ------------------------------------------------------------------
    print("[plot] world travel flows")
    cent_lat = centroid_agg["lat"].to_dict()
    cent_lon = centroid_agg["lon"].to_dict()
    top_flows = pair_counts.head(100)

    fig = plt.figure(figsize=(13, 6.5))
    ax = plt.axes(projection=ccrs.Robinson())
    add_world_features(ax)
    max_n = int(top_flows.max())
    cmap = plt.get_cmap("plasma")
    n_drawn = 0
    for (h, o), n in top_flows.items():
        if h not in cent_lat or o not in cent_lat:
            continue
        a = (cent_lat[h], cent_lon[h])
        b = (cent_lat[o], cent_lon[o])
        lw = 0.4 + 2.5 * (n / max_n)
        color = cmap(n / max_n)
        ax.plot([a[1], b[1]], [a[0], b[0]],
                transform=ccrs.Geodetic(),
                color=color, alpha=0.65, linewidth=lw, zorder=2)
        ax.scatter([a[1], b[1]], [a[0], b[0]], s=4, c="black",
                   transform=ccrs.PlateCarree(), zorder=3)
        n_drawn += 1
    sm = plt.cm.ScalarMappable(cmap=cmap,
                               norm=plt.Normalize(vmin=int(top_flows.min()), vmax=max_n))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, orientation="horizontal", pad=0.04, shrink=0.7)
    cbar.set_label("# τ travel records on this (home → OOT) pair")
    ax.set_title(f"Top-{n_drawn} home → OOT travel flows  "
                 f"(of {len(pair_counts):,} pairs total)")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "world_travel_flows.pdf", bbox_inches="tight")
    plt.close(fig)

    # ------------------------------------------------------------------
    # 10) Country distribution.
    # ------------------------------------------------------------------
    print("[plot] country distribution")
    region_country_series = pd.Series(region_country, name="country")
    cities_per_country = region_country_series.value_counts().sort_values(ascending=False)

    region_total = per_region["total"].rename("total")
    rc_df = region_total.to_frame().join(region_country_series, how="left")
    checkins_per_country = (rc_df.groupby("country")["total"].sum()
                                  .reindex(cities_per_country.index)
                                  .fillna(0))

    cap = 20  # too many countries — show top-20 in each panel
    cpc = cities_per_country.head(cap)
    chk = checkins_per_country.head(cap)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    axes[0].barh(cpc.index[::-1], cpc.values[::-1], color="#17becf")
    axes[0].set_xlabel("# regions in this dataset")
    axes[0].set_title(f"Top-{cap} countries by # regions  (total countries = {len(cities_per_country)})")
    axes[0].tick_params(axis="y", labelsize=8)

    axes[1].barh(chk.index[::-1], chk.values[::-1], color="#bcbd22")
    axes[1].set_xlabel("# check-ins (home + OOT)")
    axes[1].set_title("Top-20 countries by # check-ins")
    axes[1].tick_params(axis="y", labelsize=8)
    axes[1].set_xscale("log")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "country_distribution.pdf", bbox_inches="tight")
    plt.close(fig)

    # ------------------------------------------------------------------
    print()
    print(f"figures saved to: {OUT_DIR}")
    for p in sorted(OUT_DIR.glob("*.pdf")):
        print(f"  {p.name}")
    print()
    print("== quick stats ==")
    print(f"τ records: {len(tb):,}  ({tb.user_id.nunique():,} distinct users)")
    print(f"home check-ins: {len(home_ck):,}  oot check-ins: {len(oot_ck):,}")
    print(f"regions home: {len(home_set):,}  oot: {len(oot_set):,}  both: {len(both):,}  "
          f"only-home: {len(only_home):,}  only-oot: {len(only_oot):,}")
    print(f"unique (home → oot) pairs: {len(pair_counts):,}")
    print(f"home POI entropy median  H_norm = {home_poi_H['H_norm'].median():.3f}")
    print(f"oot  POI entropy median  H_norm = {oot_poi_H['H_norm'].median():.3f}")
    print(f"home user-act entropy median  H_norm = {home_user_H['H_norm'].median():.3f}")
    print(f"oot  user-act entropy median  H_norm = {oot_user_H['H_norm'].median():.3f}")


if __name__ == "__main__":
    main()
