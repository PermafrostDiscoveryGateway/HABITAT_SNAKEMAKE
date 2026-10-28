# Steps 3-8 for one scene, on one GPU.
#
# Needs the constants from rules/common.smk (ENV_*, SCENE_*, OUTPUT_DIR,
# FOOTPRINT, MODEL, HABITAT_*, BENCH_DIR).
rule process_scene:
    input:
        env=ENV_READY,
        scene=os.path.join(SCENE_DIR, "{scene}" + SCENE_SUFFIX),
        weights=config["weights"],
        footprint=[FOOTPRINT] if FOOTPRINT else [],
    output:
        os.path.join(OUTPUT_DIR, "{scene}_final.shp"),
    params:
        image=lambda wc: wc.scene + SCENE_SUFFIX,
        footprint=f"--footprint {FOOTPRINT}" if FOOTPRINT else "",
        device=config.get("device", "cuda"),
        no_data=config.get("no_data_value", 0),
        size=MODEL.get("size", 512),
        overlap=MODEL.get("overlap", 0.5),
        classes=MODEL.get("classes", 3),
        encoder=MODEL.get("encoder", "resnet50"),
        habitat_commit=HABITAT_COMMIT,
    log:
        "logs/process_scene/{scene}.log",
    benchmark:
        os.path.join(BENCH_DIR, "process_scene", "{scene}.tsv")
    threads: config.get("threads_per_scene", 1)
    shell:
        """
        (echo "HABITAT commit: {params.habitat_commit}"
         OMP_NUM_THREADS={threads} {ENV_PYTHON} scripts/habitat_runner.py \
            --habitat-dir {HABITAT_DIR} --scene-dir {SCENE_DIR} --output-dir {OUTPUT_DIR} \
            --weights {input.weights} --image {params.image} {params.footprint} \
            --device {params.device} --no-data-value {params.no_data} \
            --size {params.size} --overlap {params.overlap} --classes {params.classes} \
            --encoder {params.encoder}) > {log} 2>&1
        """
