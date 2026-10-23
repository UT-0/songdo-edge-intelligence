#!/usr/bin/env python3
"""Generate the OS2 (Robot Edge Controller) simulation data.

    python3 scripts/generate_os2_sim_data.py            # writes the two files below
    python3 scripts/generate_os2_sim_data.py --seed 7   # a different (still reproducible) run

Outputs (both clearly labelled, so nobody mistakes them for measured data):
  data/os2_central_park_pathway2_SAMPLE.geojson
      An APPROXIMATE waterside walking path in Songdo Central Park, drawn from the park's
      known location (node EDGE_NODE_OS2_ROBOT, 37.3925 N 126.6360 E). It is NOT a surveyed
      geometry. Replace it with a real export (OpenStreetMap / VWorld) when one is available;
      the scenario only needs a GeoJSON LineString.
  data/os2_sensor_trace_SIMULATED.csv
      One LiDAR proximity reading per 50 ms control tick. Obstacles (pedestrians, dogs,
      passing cyclists) approach and leave with a realistic distance profile plus sensor noise.
      Pedestrians and dogs come closer than 0.8 m (must trigger the e-stop); cyclists pass at
      1.0-1.8 m (must NOT trigger it).

Everything is driven by a fixed random seed, so the files are identical on every machine.
"""
import argparse
import csv
import json
import math
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH_OUT = os.path.join(ROOT, "data", "os2_central_park_pathway2_SAMPLE.geojson")
TRACE_OUT = os.path.join(ROOT, "data", "os2_sensor_trace_SIMULATED.csv")

TICK_S = 0.05
N_TICKS = 14400          # 12 minutes of 50 ms ticks: covers the 10-minute offline run + margins
STOP_BELOW_M = 0.8

# Approximate waterside path (lat, lon), walking south-east along the park's central lake.
# Hand-placed control points; smoothed below into a dense polyline.
CONTROL_POINTS = [
    (37.39470, 126.63280), (37.39420, 126.63360), (37.39385, 126.63430),
    (37.39330, 126.63500), (37.39290, 126.63560), (37.39250, 126.63600),
    (37.39205, 126.63655), (37.39160, 126.63720), (37.39120, 126.63790),
    (37.39070, 126.63850), (37.39020, 126.63905), (37.38975, 126.63970),
]

# obstacle type: (probability, closest distance range m, episode length range in ticks)
OBSTACLES = {
    "pedestrian": (0.55, (0.30, 0.75), (30, 70)),
    "dog":        (0.20, (0.25, 0.70), (16, 36)),
    "cyclist":    (0.25, (1.00, 1.80), (10, 22)),   # passes by, must not stop the robot
}


def catmull_rom(points, samples_per_segment=12):
    """Smooth the control points into a dense curve that passes through every point."""
    pts = [points[0]] + points + [points[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for s in range(samples_per_segment):
            t = s / samples_per_segment
            t2, t3 = t * t, t * t * t
            out.append(tuple(
                0.5 * (2 * p1[k] + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                       + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3)
                for k in (0, 1)))
    out.append(points[-1])
    return out


def path_length_m(line):
    total = 0.0
    for (la1, lo1), (la2, lo2) in zip(line, line[1:]):
        total += haversine_m(la1, lo1, la2, lo2)
    return total


def haversine_m(la1, lo1, la2, lo2):
    r = 6371000.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def build_trace(rng):
    """Returns a list of rows (tick, t_s, lidar_m, obstacle_id, obstacle_type)."""
    rows = []
    base = 5.0                       # free-space distance to the nearest static object (trees, edges)
    tick = 0
    obstacle_id = 0
    next_start = 6                   # first obstacle appears right away so every phase sees one
    last_type = None
    episode = None                   # (id, type, start, length, closest)
    while tick < N_TICKS:
        base = min(8.0, max(2.5, base + rng.gauss(0, 0.05)))
        d = base
        if episode is None and tick >= next_start:
            types = list(OBSTACLES)
            weights = [OBSTACLES[t][0] for t in types]
            kind = rng.choices(types, weights)[0]
            if kind == "cyclist" and last_type == "cyclist":
                kind = "pedestrian"   # never two harmless passes in a row: keeps e-stops regular
            closest = rng.uniform(*OBSTACLES[kind][1])
            length = rng.randint(*OBSTACLES[kind][2])
            if obstacle_id == 0:     # first one: a pedestrian close enough to test the e-stop at once
                kind, closest, length = "pedestrian", 0.5, 24
            obstacle_id += 1
            episode = (obstacle_id, kind, tick, length, closest)
            last_type = kind
        oid, kind = "", ""
        if episode is not None:
            eid, kind, start, length, closest = episode
            phase = (tick - start) / length                  # 0 .. 1
            # approach / hold at the closest distance (middle 20 %) / leave
            frac = min(1.0, max(0.0, abs(phase - 0.5) - 0.1) / 0.4)
            d = min(base, closest + (base - closest) * frac)
            oid = f"OBS-{eid:04d}"
            if tick - start >= length:
                episode = None
                next_start = tick + rng.randint(10, 30)
                oid, kind = "", ""
                d = base
        d = max(0.05, d + rng.gauss(0, 0.02))                # LiDAR noise (about 2 cm)
        rows.append((tick, round(tick * TICK_S, 2), round(d, 3), oid, kind))
        tick += 1
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    line = catmull_rom(CONTROL_POINTS)
    length = path_length_m(line)
    geo = {
        "type": "FeatureCollection",
        "name": "os2_central_park_pathway2_SAMPLE",
        "note": ("APPROXIMATE path drawn around Songdo Central Park's lake for the OS2 simulation. "
                 "NOT surveyed data. Replace with a real OpenStreetMap / VWorld pathway export."),
        "features": [{
            "type": "Feature",
            "id": "CENTRAL-PARK-PATHWAY-2",
            "properties": {"name": "Central Park Pathway 2 (SAMPLE)", "source": "SAMPLE",
                           "length_m": round(length, 1)},
            "geometry": {"type": "LineString",
                         "coordinates": [[round(lo, 6), round(la, 6)] for la, lo in line]},
        }],
    }
    os.makedirs(os.path.dirname(PATH_OUT), exist_ok=True)
    with open(PATH_OUT, "w") as f:
        json.dump(geo, f, indent=1)

    rows = build_trace(rng)
    with open(TRACE_OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# SIMULATED LiDAR trace for OS2 (seed %d). Not measured data." % args.seed])
        w.writerow(["tick", "t_s", "lidar_m", "obstacle_id", "obstacle_type"])
        w.writerows(rows)

    kinds = {}
    for r in rows:
        if r[3]:
            kinds.setdefault(r[4], set()).add(r[3])
    blocked = sum(1 for r in rows if r[2] < STOP_BELOW_M)
    print(f"pathway : {PATH_OUT}  ({len(line)} points, {length:.0f} m, SAMPLE)")
    print(f"trace   : {TRACE_OUT}  ({len(rows)} ticks = {len(rows) * TICK_S / 60:.0f} min, seed {args.seed})")
    print("          obstacles: " + ", ".join(f"{k} {len(v)}" for k, v in sorted(kinds.items()))
          + f"; readings below {STOP_BELOW_M} m: {blocked}")


if __name__ == "__main__":
    main()
