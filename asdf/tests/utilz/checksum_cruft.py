"""
checksum-based tests and utilities. not sure yet if these are totally useless.
holding here for now.
"""

# # dupe from asdf.format, sorry, import issues.
# def md5sum(path_or_file, hash_function=md5):
#     hasher = hash_function()
#     if isinstance(path_or_file, (str, Path)):
#         with open(path_or_file, "rb") as file_to_be_hashed:
#             hashbuffer = file_to_be_hashed.read()
#             hasher.update(hashbuffer)
#     else:
#         hasher.update(path_or_file)
#         path_or_file.seek(0)
#
#     return hasher.hexdigest()
#
#
# def overwrite_variable_columns(syspath):
#     temp = pd.read_csv(syspath)
#     for col in temp.columns:
#         if re.match(RUNTIME_VARIABLE_COLUMNS, col):
#             temp.loc[:, col] = "NULL"
#     temp.to_csv(syspath, index=False)
#
#
# def blot_gzip_timestamp(syspath):
#     with open(syspath, "rb") as zipped_file:
#         gzbytes = zipped_file.read()
#         blotbytes = gzbytes[:4] + b"\x00a\x00a" + gzbytes[8:]
#     with open(syspath, "wb") as zipped_file:
#         zipped_file.write(blotbytes)
#
#
# def make_test_checksums(case, dir_key="output_path"):
#     checksums = []
#     temp_fs = OSFS(case[dir_key])
#     for file in temp_fs.walk.files():
#         if "checksum" in file:
#             continue
#         syspath = temp_fs.getsyspath(file)
#         # NULL out csv columns that vary at runtime so they do not create
#         # spurious test failures
#         if file.endswith(".csv"):
#             overwrite_variable_columns(syspath)
#         # similarly null out gzip header timestamp
#         if file.endswith(".gz"):
#             blot_gzip_timestamp(syspath)
#         md5 = md5sum(syspath)
#         checksums.append({"file": file, "md5": md5})
#     return checksums
#


# def compare_to_reference_checksums(
#     current_df, prior_fn, fail_on_mismatch=True
# ):
#     prior_checksums = pd.read_csv(prior_fn)
#     shared = intersection(prior_checksums["file"], current_df["file"])
#     bad_comparison = False
#     if (len(shared) != len(prior_checksums["file"])) or (
#         len(shared) != len(current_df["file"])
#     ):
#         bad_comparison = True
#         rich.print("[bold red]missing or changed filenames[/]")
#         rich.print("unique to new: ")
#         for file in [
#             file for file in current_df["file"] if file not in shared
#         ]:
#             print(file)
#         rich.print("unique to old: ")
#         for file in [
#             file for file in prior_checksums["file"] if file not in shared
#         ]:
#             rich.print(f"[italic]{file}")
#     shared_slice_new = (
#         current_df.loc[current_df["file"].isin(shared)]
#         .sort_values(by="file")
#         .reset_index(drop=True)
#     )
#     shared_slice_old = (
#         prior_checksums.loc[prior_checksums["file"].isin(shared)]
#         .sort_values(by="file")
#         .reset_index(drop=True)
#     )
#     mismatches = shared_slice_new["md5"] != shared_slice_old["md5"]
#     if mismatches.any():
#         bad_comparison = True
#         rich.print("[bold red]changed checksums[/]")
#         for file in shared_slice_new.loc[mismatches]["file"]:
#             rich.print(f"[italic]{file}")
#     if bad_comparison and fail_on_mismatch:
#         raise ValueError(f"mismatches found, failing\n\n{mismatches}")

# @pytest.mark.parametrize("case_name,case", e2e_cases.items())
# def test_end_to_end_noninteractive(case_name, case):
#     asdf.cli_endpoint.asdf_initiate(
#         case["data_path"],
#         case["roi_path"],
#         output=case["output_path"],
#         config=TEST_CASE_WORKING_DIRECTORY,
#         **case["endpoint_kwargs"],
#     )
#     checksums = make_test_checksums(case)
#     checksum_df = pd.DataFrame(checksums, columns=["file", "md5"])
#     if case["checksum_path"].exists():
#         compare_to_reference_checksums(
#             checksum_df, case["checksum_path"], fail_on_mismatch=True
#         )
#     else:
#         raise FileNotFoundError(
#             "No reference checksum manifest found for this case, cannot
#             perform test."
#         )
