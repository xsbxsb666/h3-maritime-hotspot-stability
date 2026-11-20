from __future__ import annotations

import csv
import json
import math
import random
from collections import Counter
from pathlib import Path

import h3
from PIL import Image, ImageDraw, ImageFont


SEED = 20261120
RNG = random.Random(SEED)
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs_h3_report"
OUT.mkdir(exist_ok=True)


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(x))


def offset_point(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    return (
        lat + north_m / 111_320.0,
        lon + east_m / (111_320.0 * math.cos(math.radians(lat))),
    )


def ordinary_points(n_corridor: int = 6000, n_port: int = 4000) -> list[tuple[float, float]]:
    """Synthetic AIS-like points near Zhoushan: a corridor plus a port cluster."""
    pts: list[tuple[float, float]] = []
    for _ in range(n_corridor):
        t = RNG.random()
        lon = 121.75 + 0.62 * t
        lat = 29.72 + 0.34 * t + RNG.gauss(0, 0.006)
        pts.append((lat, lon))
    for _ in range(n_port):
        pts.append((29.88 + RNG.gauss(0, 0.014), 122.08 + RNG.gauss(0, 0.018)))
    RNG.shuffle(pts)
    return pts


def boundary_stress_points(center: tuple[float, float] = (29.88, 122.08)) -> tuple[str, list[tuple[float, float]]]:
    """Oversample a 600 m band around every edge of one resolution-7 cell."""
    cell = h3.latlng_to_cell(*center, 7)
    boundary = list(h3.cell_to_boundary(cell))
    pts: list[tuple[float, float]] = []
    for i, (lat1, lon1) in enumerate(boundary):
        lat2, lon2 = boundary[(i + 1) % len(boundary)]
        for j in range(61):
            t = j / 60
            lat = lat1 + (lat2 - lat1) * t
            lon = lon1 + (lon2 - lon1) * t
            # A local normal derived from the edge tangent; exact geodesic precision is unnecessary
            # because this is a controlled stress test, not a navigation calculation.
            east_t = (lon2 - lon1) * 111_320.0 * math.cos(math.radians(lat))
            north_t = (lat2 - lat1) * 111_320.0
            norm = math.hypot(east_t, north_t)
            east_n, north_n = -north_t / norm, east_t / norm
            for d in range(-600, 601, 20):
                pts.append(offset_point(lat, lon, east_n * d, north_n * d))
    return cell, pts


def cell_path(point: tuple[float, float], coarse_res: int) -> tuple[str, str]:
    direct = h3.latlng_to_cell(*point, coarse_res)
    rolled = h3.cell_to_parent(h3.latlng_to_cell(*point, 9), coarse_res)
    return direct, rolled


def top_cells(counts: Counter[str], k: int = 10) -> list[str]:
    return [c for c, _ in counts.most_common(k)]


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 1.0


def analyze(name: str, points: list[tuple[float, float]], coarse_res: int) -> dict:
    direct_cells: list[str] = []
    rolled_cells: list[str] = []
    mismatches = 0
    for p in points:
        direct, rolled = cell_path(p, coarse_res)
        direct_cells.append(direct)
        rolled_cells.append(rolled)
        mismatches += direct != rolled

    direct_counts = Counter(direct_cells)
    rolled_counts = Counter(rolled_cells)
    td, tr = top_cells(direct_counts), top_cells(rolled_counts)
    top_d, top_r = td[0], tr[0]
    relocation = haversine_km(h3.cell_to_latlng(top_d), h3.cell_to_latlng(top_r))

    direct_density = {c: n / h3.cell_area(c, unit="km^2") for c, n in direct_counts.items()}
    rolled_density = {c: n / h3.cell_area(c, unit="km^2") for c, n in rolled_counts.items()}
    density_top_d = max(direct_density, key=direct_density.get)
    density_top_r = max(rolled_density, key=rolled_density.get)

    return {
        "scenario": name,
        "coarse_resolution": coarse_res,
        "n_points": len(points),
        "mismatch_points": mismatches,
        "path_disagreement_rate": mismatches / len(points),
        "direct_cell_count": len(direct_counts),
        "rollup_cell_count": len(rolled_counts),
        "mass_error_direct": sum(direct_counts.values()) - len(points),
        "mass_error_rollup": sum(rolled_counts.values()) - len(points),
        "top10_jaccard": jaccard(td, tr),
        "top1_direct": top_d,
        "top1_rollup": top_r,
        "top1_same": top_d == top_r,
        "top1_relocation_km": relocation,
        "density_top1_direct": density_top_d,
        "density_top1_rollup": density_top_r,
        "count_vs_density_top1_same_direct": top_d == density_top_d,
        "count_vs_density_top1_same_rollup": top_r == density_top_r,
    }


def bootstrap_top1(points: list[tuple[float, float]], coarse_res: int, path: str, b: int = 200) -> dict:
    encoded = []
    for p in points:
        direct, rolled = cell_path(p, coarse_res)
        encoded.append(direct if path == "direct" else rolled)
    winners = Counter()
    n = len(encoded)
    for _ in range(b):
        counts = Counter(encoded[RNG.randrange(n)] for _ in range(n))
        winners[counts.most_common(1)[0][0]] += 1
    top_cell, wins = winners.most_common(1)[0]
    return {
        "resolution": coarse_res,
        "path": path,
        "bootstrap_repetitions": b,
        "modal_top1_cell": top_cell,
        "modal_top1_probability": wins / b,
        "distinct_top1_cells": len(winners),
    }


def adversarial_rank_flip(points: list[tuple[float, float]], coarse_res: int = 7) -> tuple[dict, list[tuple[float, float]]]:
    """Construct a transparent stress case where path-induced reassignment flips rank 1."""
    buckets: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for p in points:
        direct, rolled = cell_path(p, coarse_res)
        if direct != rolled:
            buckets.setdefault((direct, rolled), []).append(p)
    pair = max(buckets, key=lambda x: len(buckets[x]))
    source, target = pair
    crafted: list[tuple[float, float]] = []
    for cell in (source, target):
        lat, lon = h3.cell_to_latlng(cell)
        for _ in range(1000):
            crafted.append(offset_point(lat, lon, RNG.gauss(0, 8), RNG.gauss(0, 8)))
    mismatch_pool = buckets[pair]
    for i in range(200):
        crafted.append(mismatch_pool[i % len(mismatch_pool)])
    RNG.shuffle(crafted)
    return {
        "source_direct_cell": source,
        "target_rollup_cell": target,
        "balanced_points_per_cell": 1000,
        "reassigned_points": 200,
    }, crafted


def write_svg(results: list[dict], output: Path) -> None:
    width, height = 900, 430
    margin_l, margin_b, margin_t = 95, 80, 45
    chart_h = height - margin_b - margin_t
    labels = [f"{r['scenario']} r{r['coarse_resolution']}" for r in results]
    values = [100 * r["path_disagreement_rate"] for r in results]
    max_v = max(values) or 1
    bar_w = 90
    gap = 45
    start_x = margin_l + 40
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="450" y="28" text-anchor="middle" font-family="Arial" font-size="20" font-weight="bold">H3 Path Disagreement Rate</text>',
        f'<line x1="{margin_l}" y1="{margin_t}" x2="{margin_l}" y2="{height-margin_b}" stroke="#333"/>',
        f'<line x1="{margin_l}" y1="{height-margin_b}" x2="{width-35}" y2="{height-margin_b}" stroke="#333"/>',
    ]
    for tick in range(6):
        y = height - margin_b - chart_h * tick / 5
        v = max_v * tick / 5
        lines.append(f'<line x1="{margin_l-5}" y1="{y:.1f}" x2="{width-35}" y2="{y:.1f}" stroke="#ddd"/>')
        lines.append(f'<text x="{margin_l-10}" y="{y+5:.1f}" text-anchor="end" font-family="Arial" font-size="13">{v:.2f}%</text>')
    colors = ["#3b82f6", "#60a5fa", "#f59e0b", "#fbbf24"]
    for i, (label, value) in enumerate(zip(labels, values)):
        x = start_x + i * (bar_w + gap)
        h = chart_h * value / max_v
        y = height - margin_b - h
        lines.append(f'<rect x="{x}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}" fill="{colors[i % len(colors)]}" rx="4"/>')
        lines.append(f'<text x="{x+bar_w/2}" y="{y-8:.1f}" text-anchor="middle" font-family="Arial" font-size="14">{value:.3f}%</text>')
        lines.append(f'<text x="{x+bar_w/2}" y="{height-margin_b+25}" text-anchor="middle" font-family="Arial" font-size="13">{label}</text>')
    lines.append(f'<text transform="translate(22,{height/2}) rotate(-90)" text-anchor="middle" font-family="Arial" font-size="14">mismatched points (%)</text>')
    lines.append('</svg>')
    output.write_text("\n".join(lines), encoding="utf-8")


def write_png(results: list[dict], output: Path) -> None:
    width, height = 1600, 760
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=24)
    small = ImageFont.load_default(size=20)
    bold = ImageFont.load_default(size=30)
    left, right, top, bottom = 150, 60, 80, 150
    chart_h = height - top - bottom
    draw.text((width // 2, 25), "H3 Path Disagreement Rate", fill="#111827", font=bold, anchor="ma")
    draw.line((left, top, left, height - bottom), fill="#111827", width=3)
    draw.line((left, height - bottom, width - right, height - bottom), fill="#111827", width=3)
    values = [100 * r["path_disagreement_rate"] for r in results]
    max_v = max(values) * 1.15
    for i in range(6):
        y = height - bottom - chart_h * i / 5
        v = max_v * i / 5
        draw.line((left, y, width - right, y), fill="#e5e7eb", width=2)
        draw.text((left - 15, y), f"{v:.2f}%", fill="#374151", font=small, anchor="rm")
    colors = ["#2563eb", "#60a5fa", "#d97706", "#fbbf24", "#dc2626"]
    slot = (width - left - right) / len(results)
    for i, (r, value) in enumerate(zip(results, values)):
        x0 = left + slot * i + slot * 0.18
        x1 = left + slot * (i + 1) - slot * 0.18
        y = height - bottom - chart_h * value / max_v
        draw.rounded_rectangle((x0, y, x1, height - bottom), radius=8, fill=colors[i % len(colors)])
        draw.text(((x0 + x1) / 2, y - 12), f"{value:.3f}%", fill="#111827", font=small, anchor="ms")
        label1 = r["scenario"].replace("boundary_stress", "boundary").replace("adversarial_rank_flip", "rank-flip")
        draw.text(((x0 + x1) / 2, height - bottom + 28), label1, fill="#374151", font=small, anchor="ma")
        draw.text(((x0 + x1) / 2, height - bottom + 58), f"r{r['coarse_resolution']}", fill="#374151", font=small, anchor="ma")
    draw.text((left, 58), "mismatched points (%)", fill="#374151", font=small, anchor="la")
    img.save(output, dpi=(180, 180))


def main() -> None:
    ordinary = ordinary_points()
    boundary_cell, stress = boundary_stress_points()
    adversarial_meta, adversarial = adversarial_rank_flip(stress)
    results = []
    for name, pts in [("ordinary", ordinary), ("boundary_stress", stress)]:
        for res in (7, 5):
            results.append(analyze(name, pts, res))
    results.append(analyze("adversarial_rank_flip", adversarial, 7))

    boot = [bootstrap_top1(ordinary, 7, path) for path in ("direct", "rollup")]
    payload = {
        "seed": SEED,
        "h3_python_version": h3.__version__,
        "stress_target_r7_cell": boundary_cell,
        "adversarial_design": adversarial_meta,
        "results": results,
        "bootstrap": boot,
    }
    (OUT / "experiment_results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT / "experiment_results.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    write_svg(results, OUT / "path_disagreement.svg")
    write_png(results, OUT / "path_disagreement.png")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
