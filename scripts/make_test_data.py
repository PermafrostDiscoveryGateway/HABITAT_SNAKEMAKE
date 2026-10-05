"""Create a small synthetic scene, footprint and untrained model for smoke tests.

The model has random weights, so the output polygons mean nothing; this only
checks that the workflow runs from scene to shapefile.

Usage:
    python scripts/make_test_data.py --scene OUT.tif --footprint OUT.shp --weights OUT.pth
"""

import argparse
import os

import geopandas as gpd
import numpy as np
import rasterio
import segmentation_models_pytorch as smp
import torch
from rasterio.transform import from_origin
from shapely.geometry import box


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--scene", required=True)
    p.add_argument("--footprint", required=True)
    p.add_argument("--weights", required=True)
    p.add_argument("--pixels", type=int, default=1024, help="scene width and height")
    p.add_argument("--bands", type=int, default=4, help="HABITAT uses bands 2-4 (G, R, NIR)")
    p.add_argument("--classes", type=int, default=3)
    p.add_argument("--encoder", default="resnet50")
    p.add_argument("--seed", type=int, default=0)
    return p.parse_args()


def main():
    args = parse_args()
    rng = np.random.default_rng(args.seed)
    torch.manual_seed(args.seed)
    for path in (args.scene, args.footprint, args.weights):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    # 0.5 m pixels in EPSG:3413 (the projection HABITAT's outputs use), with
    # smooth structure plus noise so tiles aren't uniform.
    n = args.pixels
    yy, xx = np.mgrid[0:n, 0:n]
    base = 800 + 300 * np.sin(xx / 37.0) * np.cos(yy / 53.0)
    data = np.stack([base + rng.normal(0, 60, (n, n)) + 100 * b for b in range(args.bands)])
    data = np.clip(data, 1, 65535).astype("uint16")  # 0 is NoData

    transform = from_origin(-2_200_000.0, 200_000.0, 0.5, 0.5)
    with rasterio.open(args.scene, "w", driver="GTiff", width=n, height=n, count=args.bands,
                       dtype="uint16", crs="EPSG:3413", transform=transform, nodata=0) as dst:
        dst.write(data)

    # Footprint covering most of the scene, keyed by file name like the
    # Maxar footprint files HABITAT expects.
    left, top = transform.c, transform.f
    size = n * 0.5
    geom = box(left + 0.05 * size, top - 0.95 * size, left + 0.95 * size, top - 0.05 * size)
    gpd.GeoDataFrame({"S_FILENAME": [os.path.basename(args.scene)]}, geometry=[geom],
                     crs="EPSG:3413").to_file(args.footprint)

    # Same architecture as HABITAT's operational model, untrained. HABITAT
    # loads the whole pickled model with torch.load, so save it the same way.
    model = smp.UnetPlusPlus(encoder_name=args.encoder, encoder_weights=None, in_channels=3,
                             classes=args.classes, activation="softmax")
    model.eval()
    torch.save(model, args.weights)
    print("Wrote %s, %s, %s" % (args.scene, args.footprint, args.weights))


if __name__ == "__main__":
    main()
