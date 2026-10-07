"""Write a config overlay that runs every tile of a Maxar Open Data event.

Maxar's Open Data Program (https://www.maxar.com/open-data, CC BY-NC 4.0)
publishes each event as Analysis-Ready Data: a grid of ~5 km square tiles,
each with an 8-band multispectral COG, a panchromatic COG and a STAC item
(JSON) giving its bounds, cloud cover and data area. This lists the items
under events/<event>/ard/ in the public bucket, keeps one acquisition per
tile (least cloud, then most data, then nearest nadir), and writes a YAML
file with `scenes` and `maxar_open_samples` entries that cover each whole
tile. The download_imagery rule then builds one scene per tile and each
becomes its own process_scene job.

Use it as a second config file after your usual one; its keys replace
`scenes` and add to `maxar_open_samples`:
    python scripts/list_maxar_open_tiles.py --event NWT-Canada-Aug-23 \
        --out config/tiles.nwt.yaml
    snakemake --configfile config/config.delta.yaml config/tiles.nwt.yaml ...

Needs pyproj and PyYAML (both in the HABITAT environment).
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import yaml
from pyproj import Transformer

BUCKET = "https://maxar-opendata.s3.amazonaws.com"
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
# events/<event>/ard/<utm zone>/<quadkey>/<yyyy-mm-dd>/<catalog id>.json
ITEM_KEY = re.compile(r"/ard/\d+/\d+/\d{4}-\d{2}-\d{2}/[0-9A-Fa-f]+\.json$")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--event", required=True,
                   help="event folder in the bucket, e.g. NWT-Canada-Aug-23")
    p.add_argument("--out", required=True, help="YAML file to write")
    p.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"),
                   help="only tiles whose centre is in this lon/lat box")
    p.add_argument("--max-cloud", type=float, default=10,
                   help="skip acquisitions with more cloud than this percent (default 10)")
    p.add_argument("--min-data", type=float, default=80,
                   help="skip acquisitions covering less than this percent of the tile "
                        "(default 80; the fetch step needs at least 50)")
    p.add_argument("--limit", type=int, help="keep at most this many tiles")
    return p.parse_args()


def list_keys(prefix):
    """All object keys under prefix in the public bucket (ListObjectsV2)."""
    keys, token = [], None
    while True:
        query = {"list-type": "2", "prefix": prefix}
        if token:
            query["continuation-token"] = token
        with urllib.request.urlopen(BUCKET + "/?" + urllib.parse.urlencode(query)) as r:
            root = ET.fromstring(r.read())
        keys += [c.findtext(S3_NS + "Key") for c in root.iter(S3_NS + "Contents")]
        token = root.findtext(S3_NS + "NextContinuationToken")
        if not token:
            return keys


@lru_cache
def to_lonlat(epsg):
    return Transformer.from_crs(epsg, 4326, always_xy=True)


def fetch_item(key):
    with urllib.request.urlopen(BUCKET + "/" + key) as r:
        return key, json.load(r)


def scene_entry(key, item):
    props = item["properties"]
    left, bottom, right, top = props["proj:bbox"]
    res = 0.5  # output pixel size used by fetch_maxar_open_sample.py
    # Centre of the tile in lon/lat; the fetch script projects it back. Stay a
    # pixel inside the edges so the round trip can't push the window outside.
    lon, lat = to_lonlat(props["proj:epsg"]).transform((left + right) / 2, (bottom + top) / 2)
    size_m = min(right - left, top - bottom) - 2 * res
    tile_km2 = (right - left) * (top - bottom) / 1e6
    base = BUCKET + "/" + key[:-len(".json")]
    return {
        "quadkey": props["quadkey"],
        "name": "%s_%s_%s" % (props["quadkey"], props["platform"].lower(),
                              props["datetime"][:10].replace("-", "")),
        "cloud": props.get("tile:clouds_percent", 0),
        "data": 100 * props.get("tile:data_area", tile_km2) / tile_km2,
        "off_nadir": props.get("view:off_nadir", 0),
        "sample": {
            "ms_url": base + "-ms.tif",
            "pan_url": base + "-pan.tif",
            "lon": round(lon, 6),
            "lat": round(lat, 6),
            "size_m": int(size_m),
        },
    }


def main():
    args = parse_args()
    prefix = "events/%s/ard/" % args.event
    keys = [k for k in list_keys(prefix) if ITEM_KEY.search(k)]
    if not keys:
        raise SystemExit("No ARD items under %s/%s" % (BUCKET, prefix))
    with ThreadPoolExecutor(16) as pool:
        entries = [scene_entry(k, item) for k, item in pool.map(fetch_item, keys)]
    print("%d acquisitions over %d tiles in %s" % (
        len(entries), len({e["quadkey"] for e in entries}), args.event), file=sys.stderr)

    entries = [e for e in entries
               if e["cloud"] <= args.max_cloud and e["data"] >= args.min_data]
    if args.bbox:
        w, s, e_, n = args.bbox
        entries = [e for e in entries
                   if w <= e["sample"]["lon"] <= e_ and s <= e["sample"]["lat"] <= n]

    best = {}
    for e in sorted(entries, key=lambda e: (e["cloud"], -e["data"], e["off_nadir"])):
        best.setdefault(e["quadkey"], e)
    chosen = sorted(best.values(), key=lambda e: e["name"])[:args.limit]
    if not chosen:
        raise SystemExit("No tiles left after filtering")

    for e in chosen:
        print("  %-32s cloud %3.0f%%  data %3.0f%%" % (e["name"], e["cloud"], e["data"]),
              file=sys.stderr)

    overlay = {
        "scenes": [e["name"] for e in chosen],
        "maxar_open_samples": {e["name"]: e["sample"] for e in chosen},
    }
    header = ("# Generated by scripts/list_maxar_open_tiles.py from Maxar Open Data\n"
              "# event %s (CC BY-NC 4.0): %d whole ~5 km tiles, one scene each.\n"
              "# Pass after the main config: --configfile <main>.yaml %s\n"
              % (args.event, len(chosen), args.out))
    with open(args.out, "w") as f:
        f.write(header)
        yaml.safe_dump(overlay, f, sort_keys=False, width=200)
    print("Wrote %d tiles to %s" % (len(chosen), args.out), file=sys.stderr)


if __name__ == "__main__":
    main()
