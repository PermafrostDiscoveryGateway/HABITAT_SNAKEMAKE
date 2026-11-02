# Where scenes come from when they aren't already on disk: the smoke test's
# synthetic inputs, and Maxar Open Data samples (step 2). Both are local rules: on
# a cluster they run where snakemake runs, which has internet access.
#
# Shell commands take everything from params/input, not from the globals of the
# rule files: inside a module, Snakemake formats a shell command without them.
#
# Needs ENV_READY, ENV_PYTHON, SCENE_DIR, SCENE_SUFFIX and BENCH_DIR from
# rules/common.smk.

MAKE_TEST_DATA = repo_file("../scripts/make_test_data.py")
FETCH_MAXAR_SAMPLE = repo_file("../scripts/fetch_maxar_open_sample.py")


# Not a pipeline step: synthetic inputs referenced by config/config.test.yaml.
rule make_test_data:
    localrule: True
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
    params:
        python=ENV_PYTHON,
        script=MAKE_TEST_DATA,
    shell:
        """
        {params.python} {params.script:q} --scene {output.scene} \
            --footprint {output.footprint} --weights {output.weights} > {log} 2>&1
        """


# The smoke test's untrained model comes from make_test_data, not a download.
ruleorder: make_test_data > download_model


# Step 2. Test scenes cut from Maxar Open Data, listed under maxar_open_samples in
# the config (see config/config.sample.yaml).
SAMPLES = config.get("maxar_open_samples") or {}


rule download_imagery:
    localrule: True
    input:
        ENV_READY,
    output:
        os.path.join(SCENE_DIR, "{sample}" + SCENE_SUFFIX),
    wildcard_constraints:
        sample="|".join(SAMPLES) or "^$",
    params:
        s=lambda wc: SAMPLES[wc.sample],
        python=ENV_PYTHON,
        script=FETCH_MAXAR_SAMPLE,
    log:
        "logs/download_imagery/{sample}.log",
    benchmark:
        os.path.join(BENCH_DIR, "download_imagery", "{sample}.tsv")
    shell:
        """
        {params.python} {params.script:q} \
            --ms-url {params.s[ms_url]} --pan-url {params.s[pan_url]} \
            --lon {params.s[lon]} --lat {params.s[lat]} --size-m {params.s[size_m]} \
            --out {output} > {log} 2>&1
        """
