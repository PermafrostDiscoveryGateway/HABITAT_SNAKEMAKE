"""Build a HABITAT-style test scene from Maxar Open Data.

Maxar's Open Data Program (https://www.maxar.com/open-data, CC BY-NC 4.0)
publishes Analysis-Ready Data tiles as cloud-optimized GeoTIFFs: an 8-band
multispectral image (~1.2 m) and a panchromatic image (~0.3 m). HABITAT was
trained on 4-band (Blue, Green, Red, NIR) pansharpened scenes at ~0.5 m, so
this reads only a window around a point from each file, pansharpens the
Blue/Green/Red/NIR1 bands with the panchromatic band, and writes a 4-band
uint16 GeoTIFF in that layout.

This approximates PGC's pansharpened products well enough to check that
HABITAT finds infrastructure in real imagery; it is not their processing.

Usage:
    python scripts/fetch_maxar_open_sample.py --ms-url ...-ms.tif --pan-url ...-pan.tif \
        --lon -114.365 --lat 62.455 --size-m 2048 --out data/sample/scenes/scene.tif
"""

import argparse
import os

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform
from rasterio.windows import from_bounds

# 1-based band numbers of Blue, Green, Red, NIR1 in a WorldView-2/3 8-band
# image (Coastal, Blue, Green, Yellow, Red, Red Edge, NIR1, NIR2).
WV_8BAND_BGRN = [2, 3, 5, 7]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ms-url", required=True, help="8-band multispectral COG")
    p.add_argument("--pan-url", required=True, help="panchromatic COG")
    p.add_argument("--lon", type=float, required=True, help="window centre longitude")
    p.add_argument("--lat", type=float, required=True, help="window centre latitude")
    p.add_argument("--size-m", type=float, default=2048, help="window width and height in metres")
    p.add_argument("--res", type=float, default=0.5, help="output pixel size in metres")
    p.add_argument("--out", required=True)
    return p.parse_args()


def main():
    args = parse_args()
    n = int(round(args.size_m / args.res))

    with rasterio.open(args.pan_url) as pan_src, rasterio.open(args.ms_url) as ms_src:
        if pan_src.crs != ms_src.crs:
            raise SystemExit("ms and pan images are in different projections")
        crs = pan_src.crs
        xs, ys = warp_transform("EPSG:4326", crs, [args.lon], [args.lat])
        half = args.size_m / 2
        left, top = xs[0] - half, ys[0] + half
        bounds = (left, ys[0] - half, xs[0] + half, top)
        for src in (pan_src, ms_src):
            b = src.bounds
            if not (b.left <= bounds[0] and bounds[2] <= b.right
                    and b.bottom <= bounds[1] and bounds[3] <= b.top):
                raise SystemExit("Window around (%s, %s) is not inside %s"
                                 % (args.lon, args.lat, src.name))

        # Both read straight to the output grid; only the needed bytes are fetched.
        pan = pan_src.read(1, window=from_bounds(*bounds, pan_src.transform),
                           out_shape=(n, n), resampling=Resampling.average).astype("float64")
        ms = ms_src.read(WV_8BAND_BGRN, window=from_bounds(*bounds, ms_src.transform),
                         out_shape=(len(WV_8BAND_BGRN), n, n),
                         resampling=Resampling.bilinear).astype("float64")

    valid = (pan > 0) & np.all(ms > 0, axis=0)
    if valid.mean() < 0.5:
        raise SystemExit("Less than half the window has data; pick another point")

    # Brovey pansharpening, with the pan band first matched to the mean and
    # spread of the multispectral intensity so the result stays on the
    # multispectral scale.
    intensity = ms.mean(axis=0)
    pan_matched = ((pan - pan[valid].mean()) / pan[valid].std()
                   * intensity[valid].std() + intensity[valid].mean())
    ratio = np.where(valid, pan_matched / np.maximum(intensity, 1), 0)
    sharpened = np.clip(ms * ratio, 1, 65535)  # 0 is reserved for NoData
    sharpened[:, ~valid] = 0

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    profile = dict(driver="GTiff", width=n, height=n, count=4, dtype="uint16", crs=crs,
                   transform=from_origin(left, top, args.res, args.res), nodata=0)
    with rasterio.open(args.out, "w", **profile) as dst:
        dst.write(sharpened.astype("uint16"))
        dst.descriptions = ("Blue", "Green", "Red", "NIR1")
        dst.update_tags(SOURCE_MS=args.ms_url, SOURCE_PAN=args.pan_url,
                        LICENSE="Maxar Open Data, CC BY-NC 4.0")
    print("Wrote %s: %dx%d px at %.2f m, %.0f%% valid" % (args.out, n, n, args.res,
                                                          100 * valid.mean()))


if __name__ == "__main__":
    main()
