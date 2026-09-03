#!/usr/bin/env python3
"""Which DigitalOcean GPU droplet is deployable RIGHT NOW, cheapest first, nearest first.

Why this exists (the Creator, 2026-09-03): GPU availability on DO changes week to week —
the Ada that was the demo target on 08-13 has had an EMPTY region list ever since, and
the H100 turned up in ams3 unannounced. On demo day the question is not "which box did
we plan" but "which box exists today". This script answers it from the live API and
prints the exact `-var` flags; terraform itself has NO default for size/region on purpose.

    set -a; . .env; set +a            # DO_TOKEN (or export DIGITALOCEAN_TOKEN)
    python3 infra/terraform/gpu_pick.py [--spot] [--all]

Ranking: price ascending, then RTT from Hungary ascending. Only single-GPU NVIDIA
sizes (the `ai_stack` role builds whisper.cpp with nvcc — an AMD MI300X would be a
silent CPU fallback). Spot sizes are hidden unless `--spot`: a preempted droplet
mid-talk is worse than a pricier one.

ponytail: stdlib only, no doctl dependency. Self-check: `--self-test`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

API = "https://api.digitalocean.com/v2"

# RTT from Hungary in ms. MEASURED values come from the Pi (2026-08-13 tor1, 2026-08-28
# ams3); the rest are geography-based estimates good enough for ordering. A region not
# listed here sorts last, not nowhere.
RTT_MS = {
    "fra1": 25, "ams3": 44.9, "ams2": 45, "lon1": 55,
    "nyc1": 110, "nyc2": 110, "nyc3": 110, "ric1": 115, "atl1": 125,
    "mkc1": 130, "mem1": 130, "tor1": 139, "blr1": 150,
    "sfo1": 170, "sfo2": 170, "sfo3": 170, "sgp1": 200, "syd1": 300,
}
AMD_MARKERS = ("mi3",)          # gpu-mi300x1, gpu-mi325x1, gpu-mi355x1 — no CUDA
SPOT_MARKERS = ("spot",)        # -spot / -lc-spot: preemptible


def fetch(path: str, token: str) -> dict:
    req = urllib.request.Request(f"{API}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def rank(sizes: list[dict], regions_available: set[str], *, spot: bool = False,
         everything: bool = False) -> list[tuple[float, float, str, str]]:
    """-> [(price_per_hour, rtt_ms, size_slug, region)] sorted cheapest, then nearest.

    Unavailable (empty region list, or region flagged unavailable) sizes never appear:
    "recommended but undeployable" is exactly the failure this script exists to prevent.
    """
    rows = []
    for size in sizes:
        slug = size["slug"]
        if not slug.startswith("gpu-") or "x1" not in slug:
            continue                                            # single GPU only
        if not everything and any(m in slug for m in AMD_MARKERS):
            continue                                            # CUDA build needs NVIDIA
        if not spot and any(m in slug for m in SPOT_MARKERS):
            continue
        for region in size["regions"]:
            if region in regions_available:
                rows.append((float(size["price_hourly"]), RTT_MS.get(region, 999.0),
                             slug, region))
    return sorted(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--spot", action="store_true", help="include preemptible spot sizes")
    p.add_argument("--all", action="store_true", help="include AMD sizes too (no CUDA!)")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args(argv)
    if args.self_test:
        return _self_test()

    token = os.environ.get("DIGITALOCEAN_TOKEN") or os.environ.get("DO_TOKEN")
    if not token:
        print("no DIGITALOCEAN_TOKEN / DO_TOKEN in the environment (set -a; . .env; set +a)",
              file=sys.stderr)
        return 2
    sizes = fetch("/sizes?per_page=200", token)["sizes"]
    regions = {r["slug"] for r in fetch("/regions", token)["regions"] if r["available"]}
    rows = rank(sizes, regions, spot=args.spot, everything=args.all)
    if not rows:
        print("NO deployable single-GPU NVIDIA size anywhere right now.", file=sys.stderr)
        return 1

    print(f"{'size':<26} {'$/h':>6} {'region':<7} {'RTT ms':>7}   (deployable now)")
    for price, rtt, slug, region in rows:
        print(f"{slug:<26} {price:>6.2f} {region:<7} {rtt:>7.0f}")
    price, rtt, slug, region = rows[0]
    print(f"\nRECOMMENDED: {slug} in {region}  (${price:.2f}/h, ~{rtt:.0f} ms, "
          f"~${price * 24:.0f}/day if forgotten — destroy after the test)")
    print(f"\n  terraform apply -var do_gpu_size={slug} -var do_region={region}")
    return 0


def _self_test() -> int:
    """Canned payload shaped like the 2026-09-03 API answer."""
    sizes = [
        {"slug": "gpu-4000adax1-20gb", "price_hourly": 0.76, "regions": []},          # nowhere
        {"slug": "gpu-6000adax1-48gb", "price_hourly": 1.57, "regions": ["tor1"]},
        {"slug": "gpu-mi300x1-192gb", "price_hourly": 2.59, "regions": ["ams3"]},    # AMD
        {"slug": "gpu-h100x1-80gb", "price_hourly": 4.41, "regions": ["ams3", "nyc2", "tor1"]},
        {"slug": "gpu-h100x8-640gb", "price_hourly": 24.0, "regions": ["ams3"]},     # 8 GPU
        {"slug": "gpu-mi355x1-288gb-spot", "price_hourly": 4.5, "regions": ["mem1"]},
        {"slug": "gpu-h100x1-80gb-spot", "price_hourly": 1.0, "regions": ["sfo1"]},   # spot
    ]
    regions = {"ams3", "nyc2", "tor1", "mem1"}                                       # sfo1 down
    rows = rank(sizes, regions)
    assert [(r[2], r[3]) for r in rows] == [
        ("gpu-6000adax1-48gb", "tor1"),
        ("gpu-h100x1-80gb", "ams3"), ("gpu-h100x1-80gb", "nyc2"), ("gpu-h100x1-80gb", "tor1"),
    ], rows
    assert rank(sizes, regions, spot=True)[0][2] == "gpu-6000adax1-48gb"   # sfo1 unavailable
    assert rank(sizes, regions | {"sfo1"}, spot=True)[0][2] == "gpu-h100x1-80gb-spot"
    assert any(r[2].startswith("gpu-mi300") for r in rank(sizes, regions, everything=True))
    print("gpu_pick self-test OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
