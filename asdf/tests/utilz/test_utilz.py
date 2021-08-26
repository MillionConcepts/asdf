import re

from astropy.io import fits
from cytoolz import valfilter
from dustgoggles.func import disjoint, intersection
from fs.osfs import OSFS
import numpy as np
import pandas as pd
import rich
from PIL import Image


RUNTIME_VARIABLE_COLUMNS = re.compile(
    r"(ASDF_VERSION|FILE_TIMESTAMP|CREATOR|.*_PATH)"
)


def tree(root_path):
    tree_fs = OSFS(str(root_path))
    return list(tree_fs.walk.files())


def record_mismatches(results, absent, novel):
    for file in absent:
        results[file] = "missing from output"
    for file in novel:
        results[file] = "not found in reference"
    return results


def drop_variable_and_mismatched(df, mismatches) -> pd.DataFrame:
    variable_columns = [
        col for col in df.columns if re.match(RUNTIME_VARIABLE_COLUMNS, col)
    ]
    mismatched_columns = [col for col in df.columns if col in mismatches]
    return df.drop(columns=(variable_columns + mismatched_columns))


def compare_csv_files(test_path, ref_path):
    problems = []
    test_df, ref_df = pd.read_csv(test_path), pd.read_csv(ref_path)
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


def dispatched_asdf_comparison(file, test_fs, ref_fs):
    test_path, ref_path = (test_fs.getsyspath(file), ref_fs.getsyspath(file))
    if file.endswith("csv"):
        return compare_csv_files(test_path, ref_path)
    if file.endswith("png"):
        return compare_browse_images(test_path, ref_path)
    if file.endswith(".fits.gz"):
        return compare_roi_fits(test_path, ref_path)
    return [f"unknown file type"]


def compare_asdf_outputs(test_root, ref_root):
    test, reference = tree(test_root), tree(ref_root)
    problems = {}
    novel_files, absent_files = disjoint(test, reference)
    # note files that are completely new or missing
    if len(novel_files + absent_files):
        problems |= record_mismatches(problems, absent_files, novel_files)
    # do comparisons between others
    for file in intersection(test, reference):
        problems[file] = dispatched_asdf_comparison(
            file, OSFS(test_root), OSFS(ref_root)
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
