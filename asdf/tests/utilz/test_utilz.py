import re
import shutil
from unittest.mock import patch

from astropy.io import fits
from cytoolz import valfilter
from dustgoggles.func import disjoint, intersection, constant
from fs.osfs import OSFS
import numpy as np
import pandas as pd
import rich
from PIL import Image

import asdf.chatter
import asdf.cli_endpoint
import asdf.flow
import asdf.pretty

RUNTIME_VARIABLE_COLUMNS = re.compile(
    r"(ASDF_VERSION|FILE_TIMESTAMP|CREATOR|.*_PATH)"
)


def tree(root_path):
    tree_fs = OSFS(str(root_path))
    return list(tree_fs.walk.files())


def record_mismatches(results, absent, novel):
    for file in absent:
        results[file] = ["missing from output"]
    for file in novel:
        results[file] = ["not found in reference"]
    return results


def drop_variable_and_mismatched(df, mismatches) -> pd.DataFrame:
    variable_columns = [
        col for col in df.columns if re.match(RUNTIME_VARIABLE_COLUMNS, col)
    ]
    mismatched_columns = [col for col in df.columns if col in mismatches]
    return df.drop(columns=(variable_columns + mismatched_columns))


def compare_csv_files(test_path, ref_path, ignore_fields = None):
    problems = []
    test_df, ref_df = pd.read_csv(test_path), pd.read_csv(ref_path)
    if ignore_fields is not None:
        for field in ignore_fields:
            test_df = test_df.drop(columns=field, errors='ignore')
            ref_df = ref_df.drop(columns=field, errors='ignore')
    test_mismatches, ref_mismatches = disjoint(test_df.columns, ref_df.columns)
    # are we missing, or have we added, entire columns?
    if len(test_mismatches + ref_mismatches):
        for col in test_mismatches:
            problems.append(f"{col} found only in test")
        for col in ref_mismatches:
            problems.append(f"{col} found only in reference")
    # don't try to compare columns we know to be absent, or which we expect to
    # change between runs even if all inputs are the same(e.g., creation time)
    test_df_pruned = drop_variable_and_mismatched(
        test_df, test_mismatches
    ).sort_index(axis=1)
    ref_df_pruned = drop_variable_and_mismatched(
        ref_df, ref_mismatches
    ).sort_index(axis=1)

    diff = test_df_pruned == ref_df_pruned
    # remaining columns are completely equal -- quit
    if diff.all(axis=None):
        return problems
    diff = diff.loc[:, ~diff.all(axis=0).values]
    for col in diff.columns:
        problems.append(
            f"mismatched values in {col}: "
            f"{test_df.loc[~diff[col], col].values}, "
            f"{ref_df.loc[~diff[col], col].values}"
        )
    return problems


def compare_browse_images(test_path, ref_path):
    problems = []
    test_image, ref_image = (Image.open(test_path), Image.open(ref_path))
    if not (test_image.getbands() == ref_image.getbands()):
        problems.append("images have different modes or color spaces")
        return problems
    test_array, ref_array = np.array(test_image), np.array(ref_image)
    if not (test_array.shape == ref_array.shape):
        problems.append("images are different sizes")
        return problems
    diff = abs(test_array.astype(np.float32) - ref_array.astype(np.float32))
    if np.max(diff) > 2:
        if np.mean(diff) > 1.5e-5:
            problems.append(
                f"images have pixels that differ by {np.max(diff)}, > 2,"
                f" and images differ on average by {np.mean(diff)}, > 1.5e-5"
            )
    if diff[np.nonzero(diff)].size > 500:
        problems.append(f"images have > 500 mismatched pixels")
    return problems


def compare_roi_fits(test_path, ref_path):
    # TODO, maybe: make all of this a little more verbose
    problems = []
    test_fits, ref_fits = fits.open(test_path), fits.open(ref_path)
    if test_fits.info(False) != ref_fits.info(False):
        problems.append("files have mismatched hdulists")
        return problems
    for test_hdu, ref_hdu in zip(test_fits, ref_fits):
        if test_hdu.header != ref_hdu.header:
            problems.append(f"{test_hdu.name} headers mismatched")
        if not (test_hdu.data == ref_hdu.data).all():
            problems.append(f"{test_hdu.name} data mismatched")
    return problems


def dispatched_asdf_comparison(file, test_fs, ref_fs, ignore_fields=None):
    test_path, ref_path = (test_fs.getsyspath(file), ref_fs.getsyspath(file))
    if file.endswith("csv"):
        return compare_csv_files(test_path, ref_path, ignore_fields)
    if file.endswith("png"):
        return compare_browse_images(test_path, ref_path)
    if file.endswith(".fits.gz"):
        return compare_roi_fits(test_path, ref_path)
    return [f"unknown file type"]


def compare_asdf_outputs(test_root, ref_root, ignore_fields=None):
    test, reference = tree(test_root), tree(ref_root)
    problems = {}
    novel_files, absent_files = disjoint(test, reference)
    # note files that are completely new or missing
    if len(novel_files + absent_files):
        problems |= record_mismatches(problems, absent_files, novel_files)
    # do comparisons between others
    for file in intersection(test, reference):
        problems[file] = dispatched_asdf_comparison(
            file, OSFS(test_root), OSFS(ref_root), ignore_fields
        )
    return valfilter(lambda x: x != [], problems)


def print_mismatches(absent_files, novel_files):
    rich.print("[bold red]missing or changed filenames[/]")
    rich.print("unique to new: ")
    for file in novel_files:
        rich.print(f"[italic]{file}")
    rich.print("unique to old: ")
    for file in absent_files:
        rich.print(f"[italic]{file}")


def return_first_choice(_, choices):
    return choices[0]


# TODO: why is this nonsense necessary sometimes? track this down.
def pretty_chatter_patch(obj, new):
    return (asdf.pretty, obj, new), (asdf.chatter, obj, new)


def create_fdsa_e2e_mocks():
    patch_specs = []
    patch_specs += pretty_chatter_patch("confirm_fdsa_metadata", constant("Y"))
    patch_specs += pretty_chatter_patch("confirm_fdsa_data", constant("Y"))
    return [patch.object(*spec) for spec in patch_specs]


def create_asdf_e2e_mocks(case):
    patch_specs = []
    patch_specs += pretty_chatter_patch("confirm_observation", constant("Y"))
    if "observation_choice" in case.keys():
        patch_specs += pretty_chatter_patch(
            "offer_observation_choice", constant(case["observation_choice"])
        )
    noninteractive = "noninteractive" not in case["endpoint_kwargs"].keys()
    if not noninteractive:
        oc = (
            case["observation_choice"]
            if case.get("observation_choice") is not None
            else 1
        )
        patch_specs.append(
            (asdf.chatter, "offer_observation_choice", constant(oc))
        )
    if ("ignore_unspecified_inputs" in case.keys()) and (
        "noninteractive" not in case["endpoint_kwargs"].keys()
    ):
        patch_specs.append((asdf.flow, "name_prompt", constant("TEST")))
        patch_specs.append(
            (asdf.pretty, "metadata_open_prompt", constant("TEST"))
        )
        patch_specs += pretty_chatter_patch(
            "metadata_choice_prompt", return_first_choice
        )
    return [patch.object(*spec) for spec in patch_specs]


def regen_asdf_e2e_case(case):
    if case["temp_output_path"].exists():
        shutil.rmtree(case["temp_output_path"])
    patches = create_asdf_e2e_mocks(case)
    for e2e_patch in patches:
        e2e_patch.start()
    # note: don't necessarily need to use the test version of asdf_settings
    # b/c threading is not an issue?
    asdf.cli_endpoint.asdf_initiate(
        case["input_product_path"],
        case["roi_path"],
        output=case["temp_output_path"],
        **case["endpoint_kwargs"],
    )
    for e2e_patch in patches:
        e2e_patch.stop()
    if not case["reference_output_path"].exists():
        return
    problems = compare_asdf_outputs(
        case["temp_output_path"], case["reference_output_path"]
    )
    if len(problems):
        for file, file_problems in problems.items():
            rich.print(f"[bold red] {file}:\n")
            for file_problem in file_problems:
                rich.print(f"[italic] {file_problem}")
    # checksums = make_test_checksums(case, "temp_path")
    #
    # checksum_df = pd.DataFrame(checksums, columns=["file", "md5"])
    # checksum_df.to_csv(
    #     Path(case["temp_path"], case["checksum_path"].name), index=False
    # )
