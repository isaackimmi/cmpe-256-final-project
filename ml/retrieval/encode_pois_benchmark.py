"""Person 2 Step 2: POI Semantic Encoding + CPU vs. GPU/MPS HPC Benchmark + 2D PCA Clusters.

Generates:
  - data/gold/poi_embeddings.npy            (687K x 384 float32 L2-normalized vectors)
  - data/gold/poi_embedding_ids.parquet     (aligned poi_id index)
  - reports/hpc_embedding_benchmark.csv     (CPU vs. MPS/CUDA throughput table)
  - reports/figures/05_hpc_gpu_vs_cpu_embeddings.png
  - reports/figures/06_cross_city_embedding_clusters.png

Usage:
    .venv/bin/python -m ml.retrieval.encode_pois_benchmark
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import torch
from sentence_transformers import SentenceTransformer
from sklearn.decomposition import PCA

from ml.config import DATA_GOLD_DIR, REPORTS_DIR
from ml.retrieval.semantic_retriever import build_poi_text, encode_pois


def detect_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def run_hpc_benchmark(
    sample_texts: list[str],
    model_name: str,
    batch_size: int,
    figures_dir: Path,
) -> pd.DataFrame:
    """Benchmark CPU vs. accelerator (CUDA/MPS FP32 & FP16) encoding throughput."""
    device = detect_device()
    configs: list[tuple[str, str, dict]] = [("CPU (FP32)", "cpu", {})]
    if device != "cpu":
        configs.append((f"{device.upper()} (FP32)", device, {}))
        configs.append((f"{device.upper()} (FP16)", device, {"dtype": torch.float16}))

    rows = []
    for label, dev, m_kwargs in configs:
        print(f"[HPC Benchmark] Encoding {len(sample_texts):,} POIs on `{label}` (bs={batch_size})...")
        model = SentenceTransformer(model_name, device=dev, model_kwargs=m_kwargs)
        model.max_seq_length = 64
        # Short warmup on accelerator for fair timing
        if dev != "cpu":
            _ = model.encode(sample_texts[:64], batch_size=64, normalize_embeddings=True, show_progress_bar=False)
            if dev == "mps":
                torch.mps.synchronize()
            elif dev == "cuda":
                torch.cuda.synchronize()

        t0 = time.perf_counter()
        _ = model.encode(
            sample_texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if dev == "mps":
            torch.mps.synchronize()
        elif dev == "cuda":
            torch.cuda.synchronize()
        dt = time.perf_counter() - t0
        pois_per_sec = len(sample_texts) / dt
        rows.append(
            {
                "device": label,
                "n_pois": len(sample_texts),
                "seconds": round(dt, 3),
                "pois_per_sec": round(pois_per_sec, 1),
            }
        )
        print(f"  -> {label}: {dt:.2f}s ({pois_per_sec:.1f} POIs/sec)")
        del model

    hpc_df = pd.DataFrame(rows)
    base_tps = hpc_df.iloc[0]["pois_per_sec"]
    hpc_df["speedup_vs_cpu"] = (hpc_df["pois_per_sec"] / base_tps).round(2)
    best_row = hpc_df.iloc[-1]
    print(f"[HPC Benchmark] Best speedup ({best_row['device']} vs CPU): {best_row['speedup_vs_cpu']:.2f}x")

    csv_out = REPORTS_DIR / "hpc_embedding_benchmark.csv"
    hpc_df.to_csv(csv_out, index=False)

    sns.set_theme(style="whitegrid")
    plt.figure(figsize=(8, 4.4))
    ax = sns.barplot(data=hpc_df, x="device", y="pois_per_sec", hue="device", palette="viridis", legend=False)
    for container in ax.containers:
        ax.bar_label(container, fmt="%.0f/s", padding=3, fontsize=10, fontweight="bold")
    title = (
        f"HPC Benchmark: {model_name} POI Encoding Throughput ({len(sample_texts):,} POIs)\n"
        f"({best_row['device']} Speedup: {best_row['speedup_vs_cpu']:.2f}x vs CPU)"
    )
    plt.title(title)
    plt.xlabel("Compute Device & Precision")
    plt.ylabel("POIs Encoded per Second (higher is better)")
    plt.tight_layout()
    fig_path = figures_dir / "05_hpc_gpu_vs_cpu_embeddings.png"
    plt.savefig(fig_path, dpi=150)
    plt.close()
    print(f"[Chart] Saved {fig_path}")
    return hpc_df


def plot_cross_city_clusters(pois_df: pd.DataFrame, poi_embs: np.ndarray, figures_dir: Path) -> Path:
    """Plot 2D PCA semantic clusters across London & Madrid venues."""
    city_df = pd.read_parquet(
        DATA_GOLD_DIR / "pois_clean.parquet",
        columns=["poi_id", "city_name", "venue_schema", "is_recommendable"],
    )
    target_schemas = [
        "schema:Museum",
        "schema:ArtGallery",
        "schema:Park",
        "schema:Restaurant",
        "schema:CafeOrCoffeeShop",
        "schema:Hotel",
    ]
    vis_mask = (
        city_df["city_name"].isin(["London", "Madrid"])
        & city_df["venue_schema"].isin(target_schemas)
        & city_df["is_recommendable"]
    )
    vis_df = city_df[vis_mask].copy()
    vis_embs = poi_embs[vis_df.index.to_numpy()]

    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(vis_embs)
    vis_df["pc1"] = coords[:, 0]
    vis_df["pc2"] = coords[:, 1]
    vis_df["category"] = vis_df["venue_schema"].str.replace("schema:", "", regex=False)

    sns.set_theme(style="whitegrid")
    plt.figure(figsize=(10, 6))
    sns.scatterplot(
        data=vis_df,
        x="pc1",
        y="pc2",
        hue="category",
        style="city_name",
        alpha=0.75,
        s=45,
    )
    var1, var2 = pca.explained_variance_ratio_ * 100
    plt.title("Cross-City Semantic Alignment: London & Madrid POIs Cluster by Vibe, Not City")
    plt.xlabel(f"Embedding PC1 ({var1:.1f}% var)")
    plt.ylabel(f"Embedding PC2 ({var2:.1f}% var)")
    plt.legend(bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.tight_layout()
    fig_path = figures_dir / "06_cross_city_embedding_clusters.png"
    plt.savefig(fig_path, dpi=150)
    plt.close()
    print(f"[Chart] Saved {fig_path} ({len(vis_df):,} venues plotted)")
    return fig_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Person 2 Step 2: Encode POIs + HPC Benchmark + PCA Clusters")
    parser.add_argument("--model-name", type=str, default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--bench-size", type=int, default=4000)
    parser.add_argument("--chunk-size", type=int, default=100_000)
    parser.add_argument("--max-new-chunks", type=int, default=None)
    parser.add_argument("--skip-benchmark", action="store_true")
    args = parser.parse_args()

    figures_dir = REPORTS_DIR / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    # 1. HPC Benchmark on a sample of POIs
    if not args.skip_benchmark:
        sample_df = pd.read_parquet(
            DATA_GOLD_DIR / "pois_clean.parquet",
            columns=["name", "venue_schema", "google_categories"],
        ).head(args.bench_size)
        sample_texts = build_poi_text(sample_df)
        run_hpc_benchmark(sample_texts, args.model_name, args.batch_size, figures_dir)

    # 2. Encode all 687K POIs (chunked + cached to data/gold/poi_embeddings.npy)
    pois_df, poi_embs = encode_pois(
        model_name=args.model_name,
        batch_size=args.batch_size,
        chunk_size=args.chunk_size,
        max_new_chunks=args.max_new_chunks,
    )
    if poi_embs.size == 0:
        print("[Step 2] Encoding paused at chunk checkpoint; run again to resume.")
        return
    print(f"[Embeddings] Final shape: {poi_embs.shape}, dtype: {poi_embs.dtype}")

    # 3. 2D PCA cross-city semantic alignment figure
    plot_cross_city_clusters(pois_df, poi_embs, figures_dir)


if __name__ == "__main__":
    main()
