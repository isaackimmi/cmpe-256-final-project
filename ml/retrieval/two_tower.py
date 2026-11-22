"""Person 2 Track (Stage 1B): Locality-Conditioned PyTorch Two-Tower Neural Retriever.

Architecture & Training:
  - User + Destination Context Tower:
      Inputs: all-history mean embedding (384), prior-travel mean embedding (384),
      weighted user venue-schema profile (~137), destination city affordance vector (384),
      and trip context scalars (cyclical month, history counts, city size, has_prior_travel).
      Output: L2-normalized 128-dim vector `z_u`.
  - POI Tower:
      Inputs: pretrained BGE-small embedding (384), learned venue_schema embedding (32),
      and leakage-safe POI stats from `feat_poi_stats.parquet` (11 features, computed on fold != val_fold).
      Outputs: L2-normalized 128-dim vector `z_p` + learned scalar visitability prior `b_p`.
  - Exact FAISS MIPS Compatibility:
      Score(u, c, p) = scale * <z_u, z_p> + b_p
                     = <[z_u, 1.0], [scale * z_p, b_p]>
      Indexed per destination city with `faiss.IndexFlatIP(129)`.
  - Loss:
      In-city mixed negative sampling (50% uniform + 50% pop^0.75 hard negatives strictly from
      the same destination city via O(1) Vose alias tables) with Log-Q Sampled Softmax correction
      so raw inference scores recover calibrated log P(p | u, c).

Outputs:
  - backend/artifacts/two_tower_fold{val_fold}.pt
  - reports/figures/07_two_tower_training_curve.png
  - data/preds/two_tower_fold{val_fold}.parquet

Usage:
    .venv/bin/python -m ml.retrieval.two_tower --val-fold 0 --epochs 12
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import torch
import torch.nn as nn
import torch.nn.functional as F

from ml.config import (
    ARTIFACTS_DIR,
    DATA_GOLD_DIR,
    DEFAULT_TOP_K,
    PREDS_DIR,
    RANDOM_SEED,
    REPORTS_DIR,
)

POI_NUM_COLS = [
    "log_train_tourist_visits",
    "city_pop_pct_rank",
    "tourist_ratio",
    "log_google_reviews",
    "bayesian_rating",
    "has_google_rating",
    "log_n_checkins",
    "log_n_users",
    "log_dist_to_center_km",
    "dest_cat_supply_share",
    "log_dest_city_total_pois",
]


def detect_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def build_alias_table(probs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Build Vose's O(1) alias table for discrete distribution `probs`."""
    n = len(probs)
    scaled = probs.astype(np.float64) * n
    prob_arr = np.zeros(n, dtype=np.float32)
    alias_arr = np.zeros(n, dtype=np.int32)
    small: list[int] = []
    large: list[int] = []

    for i, p in enumerate(scaled):
        if p < 1.0:
            small.append(i)
        else:
            large.append(i)

    while small and large:
        s = small.pop()
        l = large.pop()
        prob_arr[s] = float(scaled[s])
        alias_arr[s] = l
        scaled[l] = (scaled[l] + scaled[s]) - 1.0
        if scaled[l] < 1.0:
            small.append(l)
        else:
            large.append(l)

    for idx in large:
        prob_arr[idx] = 1.0
        alias_arr[idx] = idx
    for idx in small:
        prob_arr[idx] = 1.0
        alias_arr[idx] = idx

    return prob_arr, alias_arr


class LocalityTwoTower(nn.Module):
    """Locality-conditioned cross-city Two-Tower retriever with FAISS-compatible MIPS head."""

    def __init__(
        self,
        sem_dim: int = 384,
        n_schemas: int = 140,
        poi_num_dim: int = len(POI_NUM_COLS),
        ctx_num_dim: int = 6,
        schema_emb_dim: int = 32,
        out_dim: int = 128,
        dropout: float = 0.15,
    ) -> None:
        super().__init__()
        self.sem_dim = sem_dim
        self.n_schemas = n_schemas
        self.out_dim = out_dim

        self.schema_emb = nn.Embedding(n_schemas, schema_emb_dim)

        # User + Destination Context Tower
        user_in_dim = sem_dim * 3 + n_schemas + ctx_num_dim
        self.user_proj = nn.Sequential(
            nn.Linear(user_in_dim, 512),
            nn.LayerNorm(512),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(512, 256),
            nn.LayerNorm(256),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(256, out_dim),
        )
        # Residual projection from user's semantic history to preserve pretrained alignment
        self.user_sem_skip = nn.Linear(sem_dim, out_dim, bias=False)

        # POI Tower
        poi_in_dim = sem_dim + poi_num_dim + schema_emb_dim
        self.poi_proj = nn.Sequential(
            nn.Linear(poi_in_dim, 384),
            nn.LayerNorm(384),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(384, 256),
            nn.LayerNorm(256),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(256, out_dim),
        )
        self.poi_sem_skip = nn.Linear(sem_dim, out_dim, bias=False)

        # Calibrated visitability prior head b(p)
        self.poi_bias_head = nn.Sequential(
            nn.Linear(poi_num_dim + schema_emb_dim, 64),
            nn.LayerNorm(64),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(64, 1),
        )

        # Learnable logit scale (starts around 10.0)
        self.logit_scale = nn.Parameter(torch.tensor(np.log(10.0), dtype=torch.float32))

    def get_scale(self) -> torch.Tensor:
        return self.logit_scale.exp().clamp(min=1.0, max=30.0)

    def encode_user(
        self,
        u_all: torch.Tensor,
        u_travel: torch.Tensor,
        u_schema: torch.Tensor,
        dest_ctx: torch.Tensor,
        ctx_num: torch.Tensor,
    ) -> torch.Tensor:
        x = torch.cat([u_all, u_travel, dest_ctx, u_schema, ctx_num], dim=-1)
        h = self.user_proj(x) + 0.3 * self.user_sem_skip(0.5 * (u_all + u_travel))
        return F.normalize(h, dim=-1)

    def encode_poi(
        self,
        p_emb: torch.Tensor,
        p_num: torch.Tensor,
        p_schema: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        s_emb = self.schema_emb(p_schema)
        x = torch.cat([p_emb, p_num, s_emb], dim=-1)
        h = self.poi_proj(x) + 0.3 * self.poi_sem_skip(p_emb)
        pz = F.normalize(h, dim=-1)
        bias = self.poi_bias_head(torch.cat([p_num, s_emb], dim=-1)).squeeze(-1)
        return pz, bias

    def faiss_user_vectors(
        self,
        u_all: torch.Tensor,
        u_travel: torch.Tensor,
        u_schema: torch.Tensor,
        dest_ctx: torch.Tensor,
        ctx_num: torch.Tensor,
    ) -> torch.Tensor:
        uz = self.encode_user(u_all, u_travel, u_schema, dest_ctx, ctx_num)
        ones = torch.ones((uz.shape[0], 1), dtype=uz.dtype, device=uz.device)
        return torch.cat([uz, ones], dim=-1)

    def faiss_poi_vectors(
        self,
        p_emb: torch.Tensor,
        p_num: torch.Tensor,
        p_schema: torch.Tensor,
    ) -> torch.Tensor:
        pz, bias = self.encode_poi(p_emb, p_num, p_schema)
        scale = self.get_scale()
        return torch.cat([scale * pz, bias.unsqueeze(-1)], dim=-1)


@dataclass
class RetrievalWorkspace:
    """In-memory indexed tables for fast Two-Tower training and FAISS inference."""

    # All 687K POIs (needed for history lookup)
    all_poi_ids: np.ndarray
    all_poi_embs: np.ndarray  # (N_all, 384) float32

    # Recommendable POIs sorted by city_id (for contiguous city slices & O(1) alias sampling)
    rec_poi_ids: np.ndarray
    rec_region_ids: np.ndarray
    rec_city_ids: np.ndarray  # int32
    rec_all_idx: np.ndarray  # maps rec_idx -> index in all_poi_embs
    rec_schema_ids: np.ndarray  # int64
    rec_num_feats: np.ndarray  # (N_rec, 11) float32 standardized
    rec_raw_train_visits: np.ndarray  # float32
    rec_raw_local_visits: np.ndarray  # float32 (approx from tourist_ratio)
    num_mean: np.ndarray
    num_std: np.ndarray

    # Per-city index tables
    city_vocab: list[str]
    city_to_id: dict[str, int]
    city_offset: np.ndarray  # (N_cities,) int32
    city_len: np.ndarray  # (N_cities,) int32
    city_affordance: np.ndarray  # (N_cities, 384) float32
    city_total_pois: np.ndarray  # (N_cities,) float32

    # Alias sampling tables over rec POIs
    alias_prob: np.ndarray  # (N_rec,) float32
    alias_idx: np.ndarray  # (N_rec,) int32
    rec_log_q: np.ndarray  # (N_rec,) float32

    # Schema vocabulary
    schema_vocab: list[str]
    schema_to_id: dict[str, int]


def load_poi_workspace(
    val_fold: int = 0,
    schema_vocab: list[str] | None = None,
    num_mean: np.ndarray | None = None,
    num_std: np.ndarray | None = None,
    pop_alpha: float = 0.75,
    pop_mix: float = 0.5,
) -> RetrievalWorkspace:
    """Load POI embeddings + leak-free POI stats and build contiguous per-city alias tables."""
    t0 = time.perf_counter()
    emb_path = DATA_GOLD_DIR / "poi_embeddings.npy"
    idx_path = DATA_GOLD_DIR / "poi_embedding_ids.parquet"
    if not emb_path.exists() or not idx_path.exists():
        raise FileNotFoundError(
            f"Missing {emb_path}. Run `.venv/bin/python -m ml.retrieval.encode_pois_benchmark` first."
        )

    all_poi_ids = pd.read_parquet(idx_path)["poi_id"].to_numpy()
    all_poi_embs = np.load(emb_path).astype(np.float32)

    stats_df = pd.read_parquet(DATA_GOLD_DIR / "feat_poi_stats.parquet")
    # Align stats_df to all_poi_ids order
    poi_index = pd.Index(all_poi_ids, name="poi_id")
    stats_df = stats_df.set_index("poi_id").reindex(poi_index).reset_index()
    stats_df["all_idx"] = np.arange(len(stats_df), dtype=np.int32)

    rec_df = stats_df[stats_df["is_recommendable"].fillna(False)].copy()
    rec_df = rec_df.sort_values(["region_id", "poi_id"], kind="mergesort").reset_index(drop=True)

    # Schema vocabulary (index 0 = <UNK>)
    if schema_vocab is None:
        unique_schemas = sorted(rec_df["venue_schema"].dropna().unique().tolist())
        schema_vocab = ["<UNK>"] + unique_schemas
    schema_to_id = {s: i for i, s in enumerate(schema_vocab)}
    rec_schema_ids = rec_df["venue_schema"].map(lambda s: schema_to_id.get(s, 0)).to_numpy(dtype=np.int64)

    # Numeric features (leak-free from feat_poi_stats.parquet for val_fold=0)
    raw_train_visits = rec_df["train_tourist_visits"].fillna(0).to_numpy(dtype=np.float32)
    raw_num = np.column_stack(
        [
            rec_df["log_train_tourist_visits"].fillna(0.0).to_numpy(dtype=np.float32),
            rec_df["city_pop_pct_rank"].fillna(0.5).to_numpy(dtype=np.float32),
            rec_df["tourist_ratio"].fillna(0.2).to_numpy(dtype=np.float32),
            rec_df["log_google_reviews"].fillna(0.0).to_numpy(dtype=np.float32),
            rec_df["bayesian_rating"].fillna(3.98).to_numpy(dtype=np.float32),
            rec_df["has_google_rating"].fillna(False).astype(np.float32).to_numpy(),
            rec_df["log_n_checkins"].fillna(0.0).to_numpy(dtype=np.float32),
            rec_df["log_n_users"].fillna(0.0).to_numpy(dtype=np.float32),
            np.log1p(rec_df["dist_to_center_km"].fillna(5.0).clip(lower=0.0).to_numpy(dtype=np.float32)),
            rec_df["dest_cat_supply_share"].fillna(0.0).to_numpy(dtype=np.float32),
            np.log1p(rec_df["dest_city_total_pois"].fillna(1.0).clip(lower=1.0).to_numpy(dtype=np.float32)),
        ]
    ).astype(np.float32)

    if num_mean is None or num_std is None:
        num_mean = raw_num.mean(axis=0).astype(np.float32)
        num_std = (raw_num.std(axis=0) + 1e-6).astype(np.float32)
    rec_num_feats = ((raw_num - num_mean) / num_std).astype(np.float32)

    # Approximate local visits for leave-one-out adjustment if needed
    tr = rec_df["tourist_ratio"].fillna(0.2).clip(1e-4, 0.9999).to_numpy(dtype=np.float32)
    rec_raw_local_visits = np.maximum(0.0, (raw_train_visits + 1.0) / tr - raw_train_visits - 2.0).astype(np.float32)

    # Build contiguous city slices, city affordance vectors, and per-city Vose alias tables
    rec_region_ids = rec_df["region_id"].to_numpy()
    rec_all_idx = rec_df["all_idx"].to_numpy(dtype=np.int32)
    rec_poi_ids = rec_df["poi_id"].to_numpy()

    city_vocab, first_idx, counts = np.unique(rec_region_ids, return_index=True, return_counts=True)
    # Sort by first_idx (already sorted because rec_df sorted by region_id)
    order = np.argsort(first_idx)
    city_vocab = city_vocab[order].tolist()
    city_offset = first_idx[order].astype(np.int32)
    city_len = counts[order].astype(np.int32)
    city_to_id = {c: i for i, c in enumerate(city_vocab)}
    n_cities = len(city_vocab)

    rec_city_ids = np.repeat(np.arange(n_cities, dtype=np.int32), city_len)
    city_affordance = np.zeros((n_cities, all_poi_embs.shape[1]), dtype=np.float32)
    city_total_pois = city_len.astype(np.float32)

    alias_prob = np.zeros(len(rec_df), dtype=np.float32)
    alias_idx = np.zeros(len(rec_df), dtype=np.int32)
    rec_log_q = np.zeros(len(rec_df), dtype=np.float32)

    for cid in range(n_cities):
        s = int(city_offset[cid])
        m = int(city_len[cid])
        e = s + m
        # City affordance vector = L2-normalized mean of city's recommendable POI embeddings
        mean_v = all_poi_embs[rec_all_idx[s:e]].mean(axis=0)
        city_affordance[cid] = mean_v / (np.linalg.norm(mean_v) + 1e-12)

        # Mixed negative proposal Q(p | c) = (1 - pop_mix)/M + pop_mix * pop_prob
        w_pop = np.power(raw_train_visits[s:e].astype(np.float64) + 1.0, pop_alpha)
        p_pop = w_pop / w_pop.sum()
        p_unif = np.full(m, 1.0 / m, dtype=np.float64)
        q = (1.0 - pop_mix) * p_unif + pop_mix * p_pop
        q = q / q.sum()
        rec_log_q[s:e] = np.log(np.maximum(q, 1e-12)).astype(np.float32)

        p_arr, a_arr = build_alias_table(q)
        alias_prob[s:e] = p_arr
        alias_idx[s:e] = s + a_arr

    print(
        f"[Workspace] Loaded {len(rec_df):,} recommendable POIs across {n_cities:,} cities "
        f"({len(schema_vocab)} schemas) in {time.perf_counter() - t0:.1f}s"
    )
    return RetrievalWorkspace(
        all_poi_ids=all_poi_ids,
        all_poi_embs=all_poi_embs,
        rec_poi_ids=rec_poi_ids,
        rec_region_ids=rec_region_ids,
        rec_city_ids=rec_city_ids,
        rec_all_idx=rec_all_idx,
        rec_schema_ids=rec_schema_ids,
        rec_num_feats=rec_num_feats,
        rec_raw_train_visits=raw_train_visits,
        rec_raw_local_visits=rec_raw_local_visits,
        num_mean=num_mean,
        num_std=num_std,
        city_vocab=city_vocab,
        city_to_id=city_to_id,
        city_offset=city_offset,
        city_len=city_len,
        city_affordance=city_affordance,
        city_total_pois=city_total_pois,
        alias_prob=alias_prob,
        alias_idx=alias_idx,
        rec_log_q=rec_log_q,
        schema_vocab=schema_vocab,
        schema_to_id=schema_to_id,
    )


def compute_trip_user_features(
    trips_df: pd.DataFrame,
    ws: RetrievalWorkspace,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized computation of user history embeddings & schema profiles for all trips in `trips_df`.

    Returns:
        u_all_emb    : (N_trips, 384) float16
        u_travel_emb : (N_trips, 384) float16
        u_schema_dist: (N_trips, N_schemas) float16
        dest_city_ids: (N_trips,) int32
        ctx_num      : (N_trips, 6) float32
    """
    t0 = time.perf_counter()
    n_trips = len(trips_df)
    emb_dim = ws.all_poi_embs.shape[1]
    n_schemas = len(ws.schema_vocab)

    trip_ids = trips_df["trip_id"].to_numpy()
    order = np.argsort(trip_ids)
    sorted_tids = trip_ids[order]
    inv_order = np.empty_like(order)
    inv_order[order] = np.arange(n_trips)

    poi_idx_lookup = pd.Index(ws.all_poi_ids)

    # Load exploded history strictly for trips in trips_df
    hist_df = pd.read_parquet(
        DATA_GOLD_DIR / "trip_history_exploded.parquet",
        columns=["trip_id", "poi_id", "venue_schema", "is_home"],
    )
    h_tids = hist_df["trip_id"].to_numpy()
    pos = np.searchsorted(sorted_tids, h_tids)
    in_set = (pos < n_trips) & (sorted_tids[np.minimum(pos, n_trips - 1)] == h_tids)
    hist_df = hist_df[in_set]

    trip_row = order[pos[in_set]]
    poi_row = poi_idx_lookup.get_indexer(hist_df["poi_id"].to_numpy())
    valid_poi = poi_row >= 0
    trip_row = trip_row[valid_poi]
    poi_row = poi_row[valid_poi]
    is_home = hist_df["is_home"].to_numpy()[valid_poi]
    schema_idx_lookup = pd.Index(ws.schema_vocab)
    raw_sids = schema_idx_lookup.get_indexer(hist_df["venue_schema"].to_numpy()[valid_poi])
    schema_ids = np.where(raw_sids >= 0, raw_sids, 0).astype(np.int64)

    # Accumulate via torch.index_add_ (C++ parallel, ~2-4s for 15M rows)
    u_all_sum = torch.zeros((n_trips, emb_dim), dtype=torch.float32)
    u_all_cnt = np.zeros(n_trips, dtype=np.float32)
    u_trv_sum = torch.zeros((n_trips, emb_dim), dtype=torch.float32)
    u_trv_cnt = np.zeros(n_trips, dtype=np.float32)
    u_schema = np.zeros((n_trips, n_schemas), dtype=np.float32)

    all_embs_t = torch.from_numpy(ws.all_poi_embs)
    chunk = 2_000_000
    n_hist = len(trip_row)
    for start in range(0, n_hist, chunk):
        end = min(start + chunk, n_hist)
        tr_c = trip_row[start:end]
        pr_c = poi_row[start:end]
        ih_c = is_home[start:end]
        sc_c = schema_ids[start:end]

        tr_t = torch.from_numpy(tr_c.astype(np.int64))
        embs_c = all_embs_t[torch.from_numpy(pr_c.astype(np.int64))]
        u_all_sum.index_add_(0, tr_t, embs_c)
        np.add.at(u_all_cnt, tr_c, 1.0)

        trv_mask = ~ih_c
        if np.any(trv_mask):
            tr_trv = tr_c[trv_mask]
            u_trv_sum.index_add_(0, torch.from_numpy(tr_trv.astype(np.int64)), embs_c[torch.from_numpy(trv_mask)])
            np.add.at(u_trv_cnt, tr_trv, 1.0)

        # Weight prior-travel POIs 2x vs home POIs 1x in schema profile
        weights = np.where(ih_c, 1.0, 2.0).astype(np.float32)
        np.add.at(u_schema, (tr_c, sc_c), weights)

    u_all_np = u_all_sum.numpy()
    u_all_norm = np.linalg.norm(u_all_np, axis=1, keepdims=True) + 1e-12
    u_all_emb = (u_all_np / u_all_norm).astype(np.float16)

    u_trv_np = u_trv_sum.numpy()
    has_trv = u_trv_cnt > 0
    u_trv_norm = np.linalg.norm(u_trv_np, axis=1, keepdims=True) + 1e-12
    u_travel_emb = np.where(has_trv[:, None], u_trv_np / u_trv_norm, u_all_emb.astype(np.float32)).astype(np.float16)

    u_schema_sum = u_schema.sum(axis=1, keepdims=True) + 1e-12
    u_schema_dist = (u_schema / u_schema_sum).astype(np.float16)

    dest_city_ids = np.array(
        [ws.city_to_id.get(r, -1) for r in trips_df["dest_region_id"].tolist()],
        dtype=np.int32,
    )
    dest_month = trips_df["dest_month"].fillna(6).to_numpy(dtype=np.float32)
    ang = 2.0 * np.pi * (dest_month / 12.0)
    city_tot = np.where(dest_city_ids >= 0, ws.city_total_pois[np.maximum(dest_city_ids, 0)], 1.0)
    ctx_num = np.column_stack(
        [
            np.sin(ang),
            np.cos(ang),
            np.log1p(trips_df["n_history_cities"].fillna(1).to_numpy(dtype=np.float32)),
            np.log1p(trips_df["n_history_pois"].fillna(3).to_numpy(dtype=np.float32)),
            has_trv.astype(np.float32),
            np.log1p(city_tot),
        ]
    ).astype(np.float32)

    print(f"[User Features] Precomputed features for {n_trips:,} trips ({n_hist:,} history rows) in {time.perf_counter() - t0:.1f}s")
    return u_all_emb, u_travel_emb, u_schema_dist, dest_city_ids, ctx_num


@torch.no_grad()
def encode_all_rec_pois_for_faiss(
    model: LocalityTwoTower,
    ws: RetrievalWorkspace,
    device: str,
    batch_size: int = 8192,
) -> np.ndarray:
    """Encode all recommendable POIs into 129-dim FAISS MIPS vectors."""
    model.eval()
    n_rec = len(ws.rec_poi_ids)
    out = np.empty((n_rec, model.out_dim + 1), dtype=np.float32)
    for s in range(0, n_rec, batch_size):
        e = min(s + batch_size, n_rec)
        p_emb = torch.from_numpy(ws.all_poi_embs[ws.rec_all_idx[s:e]]).to(device)
        p_num = torch.from_numpy(ws.rec_num_feats[s:e]).to(device)
        p_sch = torch.from_numpy(ws.rec_schema_ids[s:e]).to(device)
        vecs = model.faiss_poi_vectors(p_emb, p_num, p_sch)
        out[s:e] = vecs.cpu().numpy()
    return out


@torch.no_grad()
def encode_trips_for_faiss(
    model: LocalityTwoTower,
    ws: RetrievalWorkspace,
    u_all_emb: np.ndarray,
    u_travel_emb: np.ndarray,
    u_schema_dist: np.ndarray,
    dest_city_ids: np.ndarray,
    ctx_num: np.ndarray,
    device: str,
    batch_size: int = 4096,
) -> np.ndarray:
    """Encode trips into 129-dim FAISS query vectors."""
    model.eval()
    n = len(dest_city_ids)
    out = np.empty((n, model.out_dim + 1), dtype=np.float32)
    for s in range(0, n, batch_size):
        e = min(s + batch_size, n)
        ua = torch.from_numpy(u_all_emb[s:e].astype(np.float32)).to(device)
        ut = torch.from_numpy(u_travel_emb[s:e].astype(np.float32)).to(device)
        us = torch.from_numpy(u_schema_dist[s:e].astype(np.float32)).to(device)
        dc = torch.from_numpy(ws.city_affordance[np.maximum(dest_city_ids[s:e], 0)]).to(device)
        cn = torch.from_numpy(ctx_num[s:e]).to(device)
        q = model.faiss_user_vectors(ua, ut, us, dc, cn)
        out[s:e] = q.cpu().numpy()
    return out


@torch.no_grad()
def _exact_mips_topk(
    queries_np: np.ndarray,
    city_mat_np: np.ndarray,
    k: int,
    device: str,
    q_batch: int = 1024,
) -> tuple[np.ndarray, np.ndarray]:
    """Exact inner-product Top-K search on `device` (identical to faiss.IndexFlatIP, zero libomp clash)."""
    mat_t = torch.from_numpy(city_mat_np).to(device)  # (M, D)
    n_q = queries_np.shape[0]
    scores_out = np.empty((n_q, k), dtype=np.float32)
    idx_out = np.empty((n_q, k), dtype=np.int32)
    for s in range(0, n_q, q_batch):
        e = min(s + q_batch, n_q)
        q_t = torch.from_numpy(queries_np[s:e]).to(device)
        dots = q_t @ mat_t.T  # (b, M)
        vals, inds = torch.topk(dots, k=k, dim=1, largest=True, sorted=True)
        scores_out[s:e] = vals.cpu().numpy()
        idx_out[s:e] = inds.cpu().numpy().astype(np.int32)
    return scores_out, idx_out


@torch.no_grad()
def evaluate_recall_at_k_faiss(
    model: LocalityTwoTower,
    ws: RetrievalWorkspace,
    trip_indices: np.ndarray,
    trip_targets: list[set[int]],
    u_all_emb: np.ndarray,
    u_travel_emb: np.ndarray,
    u_schema_dist: np.ndarray,
    dest_city_ids: np.ndarray,
    ctx_num: np.ndarray,
    device: str,
    k: int = 100,
) -> tuple[float, float]:
    """Compute exact per-city MIPS Recall@10 and Recall@100 on a subset of trips."""
    poi_vecs = encode_all_rec_pois_for_faiss(model, ws, device)
    sub_cids = dest_city_ids[trip_indices]
    q_vecs = encode_trips_for_faiss(
        model,
        ws,
        u_all_emb[trip_indices],
        u_travel_emb[trip_indices],
        u_schema_dist[trip_indices],
        sub_cids,
        ctx_num[trip_indices],
        device,
    )

    rec10_sum = 0.0
    rec100_sum = 0.0
    n_eval = 0

    df_q = pd.DataFrame({"local_pos": np.arange(len(trip_indices)), "cid": sub_cids})
    for cid, grp in df_q.groupby("cid", sort=False):
        cid_int = int(cid)
        if cid_int < 0:
            continue
        s = int(ws.city_offset[cid_int])
        m = int(ws.city_len[cid_int])
        mat = np.ascontiguousarray(poi_vecs[s : s + m], dtype=np.float32)

        lpos = grp["local_pos"].to_numpy()
        queries = np.ascontiguousarray(q_vecs[lpos], dtype=np.float32)
        kk = min(k, m)
        _, I = _exact_mips_topk(queries, mat, kk, device=device)
        global_rec_I = I + s

        for row_i, lp in enumerate(lpos):
            tset = trip_targets[lp]
            if not tset:
                continue
            preds = global_rec_I[row_i]
            hits10 = sum(1 for p in preds[:10] if int(p) in tset)
            hits100 = sum(1 for p in preds if int(p) in tset)
            rec10_sum += hits10 / len(tset)
            rec100_sum += hits100 / len(tset)
            n_eval += 1

    return rec10_sum / max(1, n_eval), rec100_sum / max(1, n_eval)


def retrieve_top_k_batched_faiss(
    model: LocalityTwoTower,
    ws: RetrievalWorkspace,
    trips_df: pd.DataFrame,
    u_all_emb: np.ndarray,
    u_travel_emb: np.ndarray,
    u_schema_dist: np.ndarray,
    dest_city_ids: np.ndarray,
    ctx_num: np.ndarray,
    device: str,
    top_k: int = DEFAULT_TOP_K,
) -> pd.DataFrame:
    """Fast batched per-city exact MIPS retrieval returning (trip_id, poi_id, score)."""
    t0 = time.perf_counter()
    poi_vecs = encode_all_rec_pois_for_faiss(model, ws, device)
    q_vecs = encode_trips_for_faiss(
        model, ws, u_all_emb, u_travel_emb, u_schema_dist, dest_city_ids, ctx_num, device
    )

    trip_ids_arr = trips_df["trip_id"].to_numpy()
    out_tids: list[np.ndarray] = []
    out_pids: list[np.ndarray] = []
    out_scores: list[np.ndarray] = []

    df_q = pd.DataFrame({"pos": np.arange(len(trips_df)), "cid": dest_city_ids})
    for cid, grp in df_q.groupby("cid", sort=False):
        cid_int = int(cid)
        if cid_int < 0:
            continue
        s = int(ws.city_offset[cid_int])
        m = int(ws.city_len[cid_int])
        mat = np.ascontiguousarray(poi_vecs[s : s + m], dtype=np.float32)

        pos_arr = grp["pos"].to_numpy()
        queries = np.ascontiguousarray(q_vecs[pos_arr], dtype=np.float32)
        kk = min(top_k, m)
        scores, local_I = _exact_mips_topk(queries, mat, kk, device=device)
        global_I = local_I + s

        out_tids.append(np.repeat(trip_ids_arr[pos_arr], kk))
        out_pids.append(ws.rec_poi_ids[global_I.ravel()])
        out_scores.append(scores.ravel().astype(np.float32))

    preds_df = pd.DataFrame(
        {
            "trip_id": np.concatenate(out_tids),
            "poi_id": np.concatenate(out_pids),
            "score": np.concatenate(out_scores),
        }
    )
    print(f"[Two-Tower MIPS] Retrieved {len(preds_df):,} candidates in {time.perf_counter() - t0:.1f}s")
    return preds_df


def train_and_evaluate(
    val_fold: int = 0,
    epochs: int = 12,
    batch_size: int = 512,
    n_neg: int = 32,
    lr: float = 2e-3,
    weight_decay: float = 1e-4,
    out_dim: int = 128,
    top_k: int = DEFAULT_TOP_K,
) -> None:
    torch.manual_seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    rng = np.random.default_rng(RANDOM_SEED)
    device = detect_device()
    print(f"[Person 2 - Stage 1B] Training LocalityTwoTower on `{device}` (val_fold={val_fold}, epochs={epochs}, n_neg={n_neg})")

    ws = load_poi_workspace(val_fold=val_fold)

    # Load all trips and split strictly: train+dev from fold != val_fold, test = val_fold
    trips_all = pd.read_parquet(DATA_GOLD_DIR / "trips_multicity.parquet")
    train_pool = trips_all[trips_all["fold"] != val_fold].reset_index(drop=True)
    val_trips = trips_all[trips_all["fold"] == val_fold].reset_index(drop=True)

    # Precompute user features for train_pool
    u_all_tr, u_trv_tr, u_sch_tr, cid_tr, ctx_tr = compute_trip_user_features(train_pool, ws)

    # Build positive target lists (in rec_idx coordinates) for every trip in train_pool
    rec_poi_lookup = pd.Index(ws.rec_poi_ids)
    targ_df = pd.read_parquet(
        DATA_GOLD_DIR / "trip_targets_exploded.parquet",
        columns=["trip_id", "poi_id", "fold"],
    )
    targ_tr = targ_df[targ_df["fold"] != val_fold]

    tr_tids = train_pool["trip_id"].to_numpy()
    tr_order = np.argsort(tr_tids)
    sorted_tr_tids = tr_tids[tr_order]

    t_pos = np.searchsorted(sorted_tr_tids, targ_tr["trip_id"].to_numpy())
    in_tr = (t_pos < len(train_pool)) & (sorted_tr_tids[np.minimum(t_pos, len(train_pool) - 1)] == targ_tr["trip_id"].to_numpy())
    pair_trip_idx = tr_order[t_pos[in_tr]].astype(np.int32)
    pair_rec_idx = rec_poi_lookup.get_indexer(targ_tr["poi_id"].to_numpy()[in_tr]).astype(np.int32)
    valid_pair = (pair_rec_idx >= 0) & (cid_tr[pair_trip_idx] >= 0)
    pair_trip_idx = pair_trip_idx[valid_pair]
    pair_rec_idx = pair_rec_idx[valid_pair]

    # User-grouped internal 5% dev split from fold != val_fold (zero leakage onto val_fold!)
    unique_users = train_pool["user_id"].unique()
    dev_users = set(rng.choice(unique_users, size=max(1, int(0.05 * len(unique_users))), replace=False).tolist())
    is_dev_trip = train_pool["user_id"].isin(dev_users).to_numpy()
    is_dev_pair = is_dev_trip[pair_trip_idx]

    tr_pair_trip = pair_trip_idx[~is_dev_pair]
    tr_pair_rec = pair_rec_idx[~is_dev_pair]
    dev_pair_trip = pair_trip_idx[is_dev_pair]
    dev_pair_rec = pair_rec_idx[is_dev_pair]

    # Build dev Recall@100 evaluation slice (up to 6,000 dev trips)
    dev_trip_ids_unique = np.unique(dev_pair_trip)
    if len(dev_trip_ids_unique) > 6000:
        dev_eval_trips = rng.choice(dev_trip_ids_unique, size=6000, replace=False)
    else:
        dev_eval_trips = dev_trip_ids_unique
    dev_eval_set = set(dev_eval_trips.tolist())
    dev_targets_map: dict[int, set[int]] = {int(t): set() for t in dev_eval_trips}
    for ti, ri in zip(dev_pair_trip, dev_pair_rec):
        t_int = int(ti)
        if t_int in dev_eval_set:
            dev_targets_map[t_int].add(int(ri))
    dev_eval_targets = [dev_targets_map[int(t)] for t in dev_eval_trips]

    print(
        f"[Split] Train pairs: {len(tr_pair_trip):,} | Internal dev pairs: {len(dev_pair_trip):,} "
        f"| Dev FAISS eval trips: {len(dev_eval_trips):,}"
    )

    model = LocalityTwoTower(
        sem_dim=ws.all_poi_embs.shape[1],
        n_schemas=len(ws.schema_vocab),
        poi_num_dim=ws.rec_num_feats.shape[1],
        ctx_num_dim=ctx_tr.shape[1],
        out_dim=out_dim,
    ).to(device)

    # Move compact POI lookup arrays to GPU/MPS if memory allows (535K x 384 fp16 = ~411MB!)
    rec_embs_f16 = torch.from_numpy(ws.all_poi_embs[ws.rec_all_idx].astype(np.float16)).to(device)
    rec_num_t = torch.from_numpy(ws.rec_num_feats).to(device)
    rec_sch_t = torch.from_numpy(ws.rec_schema_ids).to(device)
    rec_log_q_t = torch.from_numpy(ws.rec_log_q).to(device)

    # Precompute leave-one-out adjusted log_train_tourist_visits (col 0) & tourist_ratio (col 2) for training positives
    loo_visits = np.maximum(0.0, ws.rec_raw_train_visits - 1.0)
    loo_log_visits = (np.log1p(loo_visits) - ws.num_mean[0]) / ws.num_std[0]
    loo_tr = ((loo_visits + 1.0) / (loo_visits + ws.rec_raw_local_visits + 2.0) - ws.num_mean[2]) / ws.num_std[2]
    loo_log_visits_t = torch.from_numpy(loo_log_visits.astype(np.float32)).to(device)
    loo_tr_t = torch.from_numpy(loo_tr.astype(np.float32)).to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    # Cap steps per epoch to ~350K pairs (sampled without replacement each epoch) so 12 epochs finishes quickly & smoothly
    pairs_per_epoch = min(len(tr_pair_trip), 360_000)
    steps_per_epoch = pairs_per_epoch // batch_size
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs * steps_per_epoch, eta_min=1e-4)

    def sample_incity_negatives(batch_cids: np.ndarray, k_neg: int) -> np.ndarray:
        offsets = ws.city_offset[batch_cids][:, None]
        lens = ws.city_len[batch_cids][:, None]
        slots = offsets + (rng.random((len(batch_cids), k_neg)) * lens).astype(np.int32)
        slots = np.minimum(slots, offsets + lens - 1)
        use_slot = rng.random((len(batch_cids), k_neg)) < ws.alias_prob[slots]
        return np.where(use_slot, slots, ws.alias_idx[slots]).astype(np.int64)

    def run_batch(
        b_tidx: np.ndarray,
        b_pos: np.ndarray,
        training: bool,
    ) -> torch.Tensor:
        b_cids = cid_tr[b_tidx]
        b_negs = sample_incity_negatives(b_cids, n_neg)  # (B, K)

        ua = torch.from_numpy(u_all_tr[b_tidx].astype(np.float32)).to(device)
        ut = torch.from_numpy(u_trv_tr[b_tidx].astype(np.float32)).to(device)
        us = torch.from_numpy(u_sch_tr[b_tidx].astype(np.float32)).to(device)
        dc = torch.from_numpy(ws.city_affordance[b_cids]).to(device)
        cn = torch.from_numpy(ctx_tr[b_tidx]).to(device)

        uz = model.encode_user(ua, ut, us, dc, cn)  # (B, D)

        pos_t = torch.from_numpy(b_pos.astype(np.int64)).to(device)
        neg_t = torch.from_numpy(b_negs).to(device)  # (B, K)
        cand_idx = torch.cat([pos_t.unsqueeze(1), neg_t], dim=1)  # (B, 1+K)
        flat_idx = cand_idx.reshape(-1)

        p_emb = rec_embs_f16[flat_idx].float()
        p_num = rec_num_t[flat_idx].clone()
        p_sch = rec_sch_t[flat_idx]

        # Leave-one-out subtraction on the positive POI during training to prevent self-count leakage
        if training:
            pos_flat_positions = torch.arange(0, len(flat_idx), 1 + n_neg, device=device)
            p_num[pos_flat_positions, 0] = loo_log_visits_t[pos_t]
            p_num[pos_flat_positions, 2] = loo_tr_t[pos_t]

        pz, pb = model.encode_poi(p_emb, p_num, p_sch)
        pz = pz.view(len(b_tidx), 1 + n_neg, -1)
        pb = pb.view(len(b_tidx), 1 + n_neg)

        scale = model.get_scale()
        raw_scores = scale * torch.einsum("bd,bkd->bk", uz, pz) + pb

        # Log-Q Sampled Softmax correction so raw_scores -> calibrated log P(p | u, c)
        log_q = rec_log_q_t[cand_idx]
        logits = raw_scores - log_q

        # Mask accidental negative collisions where neg == pos
        collision = neg_t == pos_t.unsqueeze(1)
        logits[:, 1:] = logits[:, 1:].masked_fill(collision, -1e4)

        targets = torch.zeros(len(b_tidx), dtype=torch.long, device=device)
        return F.cross_entropy(logits, targets)

    history = []
    best_recall100 = -1.0
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    ckpt_path = ARTIFACTS_DIR / f"two_tower_fold{val_fold}.pt"

    for epoch in range(1, epochs + 1):
        t_ep = time.perf_counter()
        model.train()
        perm = rng.choice(len(tr_pair_trip), size=pairs_per_epoch, replace=False)
        tr_loss_sum = 0.0
        n_steps = 0

        for step in range(steps_per_epoch):
            sl = perm[step * batch_size : (step + 1) * batch_size]
            optimizer.zero_grad(set_to_none=True)
            loss = run_batch(tr_pair_trip[sl], tr_pair_rec[sl], training=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            optimizer.step()
            scheduler.step()
            tr_loss_sum += float(loss.item())
            n_steps += 1

        # Internal dev loss
        model.eval()
        dev_loss_sum = 0.0
        dev_steps = 0
        dev_perm = np.arange(min(len(dev_pair_trip), 30_000))
        with torch.no_grad():
            for s in range(0, len(dev_perm), batch_size):
                sl = dev_perm[s : s + batch_size]
                if len(sl) < 16:
                    continue
                dloss = run_batch(dev_pair_trip[sl], dev_pair_rec[sl], training=False)
                dev_loss_sum += float(dloss.item())
                dev_steps += 1

        dev_r10, dev_r100 = evaluate_recall_at_k_faiss(
            model,
            ws,
            dev_eval_trips,
            dev_eval_targets,
            u_all_tr,
            u_trv_tr,
            u_sch_tr,
            cid_tr,
            ctx_tr,
            device,
            k=100,
        )

        tr_loss = tr_loss_sum / max(1, n_steps)
        dev_loss = dev_loss_sum / max(1, dev_steps)
        dt = time.perf_counter() - t_ep
        scale_val = float(model.get_scale().item())
        history.append(
            {
                "epoch": epoch,
                "train_loss": tr_loss,
                "dev_loss": dev_loss,
                "dev_recall_10": dev_r10,
                "dev_recall_100": dev_r100,
                "scale": scale_val,
                "seconds": dt,
            }
        )
        marker = ""
        if dev_r100 > best_recall100:
            best_recall100 = dev_r100
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "config": {
                        "sem_dim": ws.all_poi_embs.shape[1],
                        "n_schemas": len(ws.schema_vocab),
                        "poi_num_dim": ws.rec_num_feats.shape[1],
                        "ctx_num_dim": ctx_tr.shape[1],
                        "out_dim": out_dim,
                    },
                    "schema_vocab": ws.schema_vocab,
                    "num_mean": ws.num_mean,
                    "num_std": ws.num_std,
                    "val_fold": val_fold,
                    "best_dev_recall_100": best_recall100,
                    "epoch": epoch,
                },
                ckpt_path,
            )
            marker = " *saved*"
        print(
            f"Epoch {epoch:02d}/{epochs} ({dt:.1f}s) | train_loss={tr_loss:.4f} | "
            f"dev_loss={dev_loss:.4f} | dev_R@10={dev_r10:.5f} | dev_R@100={dev_r100:.5f} "
            f"| scale={scale_val:.2f}{marker}"
        )

    # Save training curve figure (2-panel: Loss + Dev Recall@100 Progression)
    hist_df = pd.DataFrame(history)
    figures_dir = REPORTS_DIR / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    hist_df.to_csv(REPORTS_DIR / f"two_tower_history_fold{val_fold}.csv", index=False)

    sns.set_theme(style="whitegrid")
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6))

    axes[0].plot(hist_df["epoch"], hist_df["train_loss"], marker="o", label="Train Log-Q Loss")
    axes[0].plot(hist_df["epoch"], hist_df["dev_loss"], marker="s", label="Internal Dev Loss")
    axes[0].set_title("Locality Two-Tower Training & Dev Loss")
    axes[0].set_xlabel("Epoch")
    axes[0].set_ylabel("Sampled Softmax Cross-Entropy")
    axes[0].legend()

    axes[1].plot(hist_df["epoch"], hist_df["dev_recall_100"], marker="o", color="#2a9d8f", linewidth=2.2, label="Two-Tower Dev Recall@100")
    axes[1].axhline(0.69014, color="#e76f51", linestyle="--", linewidth=1.6, label="Popularity Baseline Recall@100 (0.69014)")
    axes[1].set_title("FAISS Retrieval Recall@100 Progression")
    axes[1].set_xlabel("Epoch")
    axes[1].set_ylabel("Recall@100")
    axes[1].legend()

    plt.tight_layout()
    fig_path = figures_dir / "07_two_tower_training_curve.png"
    plt.savefig(fig_path, dpi=150)
    plt.close()
    print(f"[Chart] Saved {fig_path}")

    # Load best checkpoint and run full fold_0 FAISS Top-100 inference
    best_ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    model.load_state_dict(best_ckpt["state_dict"])
    print(f"[Inference] Loaded best checkpoint from epoch {best_ckpt['epoch']} (dev_R@100={best_ckpt['best_dev_recall_100']:.5f})")

    u_all_va, u_trv_va, u_sch_va, cid_va, ctx_va = compute_trip_user_features(val_trips, ws)
    preds_df = retrieve_top_k_batched_faiss(
        model,
        ws,
        val_trips,
        u_all_va,
        u_trv_va,
        u_sch_va,
        cid_va,
        ctx_va,
        device=device,
        top_k=top_k,
    )

    PREDS_DIR.mkdir(parents=True, exist_ok=True)
    preds_out = PREDS_DIR / f"two_tower_fold{val_fold}.parquet"
    preds_df.to_parquet(preds_out, index=False)
    print(f"[Person 2] Saved Stage 1B Two-Tower predictions -> {preds_out}")
    print(
        f"Next: .venv/bin/python -m ml.evaluate --preds {preds_out} "
        f"--name two_tower_v1 --author person2 --fold {val_fold}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Train & evaluate Person 2 Locality-Conditioned Two-Tower Retriever.")
    parser.add_argument("--val-fold", type=int, default=0)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--n-neg", type=int, default=32)
    parser.add_argument("--lr", type=float, default=2e-3)
    parser.add_argument("--out-dim", type=int, default=128)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    args = parser.parse_args()
    train_and_evaluate(
        val_fold=args.val_fold,
        epochs=args.epochs,
        batch_size=args.batch_size,
        n_neg=args.n_neg,
        lr=args.lr,
        out_dim=args.out_dim,
        top_k=args.top_k,
    )


if __name__ == "__main__":
    main()
