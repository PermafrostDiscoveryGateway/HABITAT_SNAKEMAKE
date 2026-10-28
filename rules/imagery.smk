# Where scenes come from when they aren't already on disk: the smoke test's
# synthetic inputs, and Maxar Open Data samples (step 2). Both are localrules
# (see the Snakefile).
#
# Needs ENV_READY, ENV_PYTHON, SCENE_DIR, SCENE_SUFFIX and BENCH_DIR from
# rules/common.smk.


# Not a pipeline step: synthetic inputs referenced by config/config.test.yaml.
rule make_test_data:
    input:
        ENV_READY,
    output:
        scene="test_data/scenes/synthetic_scene.tif",
        footprint="test_data/footprints/footprints.shp",
        weights="test_data/weights/untrained_unetpp.pth",
    log:
        "logs/make_test_data.log",
    benchmark:
        os.path.join(BENCH_DIR, "make_test_data.tsv")
    shell:
        """
        {ENV_PYTHON} scripts/make_test_data.py --scene {output.scene} \
            --footprint {output.footprint} --weights {output.weights} > {log} 2>&1
        """


# The smoke test's untrained model comes from make_test_data, not a download.
ruleorder: make_test_data > download_model


# Step 2. Test scenes cut from Maxar Open Data, listed under maxar_open_samples in
# the config (see config/config.sample.yaml).
SAMPLES = config.get("maxar_open_samples") or {}


rule download_imagery:
    input:
        ENV_READY,
    output:
        os.path.join(SCENE_DIR, "{sample}" + SCENE_SUFFIX),
    wildcard_constraints:
        sample="|".join(SAMPLES) or "^$",
    params:
        s=lambda wc: SAMPLES[wc.sample],
    log:
        "logs/download_imagery/{sample}.log",
    benchmark:
        os.path.join(BENCH_DIR, "download_imagery", "{sample}.tsv")
    shell:
        """
        {ENV_PYTHON} scripts/fetch_maxar_open_sample.py \
            --ms-url {params.s[ms_url]} --pan-url {params.s[pan_url]} \
            --lon {params.s[lon]} --lat {params.s[lat]} --size-m {params.s[size_m]} \
            --out {output} > {log} 2>&1
        """
