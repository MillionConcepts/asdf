Observational data files for test cases should go into this directory.

Current cases:

sol 0046 / zcam03110
* regularish, clear filters deleted, picks first option

sol 0046_co / zcam03110
* as above, but narrowband filters deleted instead (passes keep_broadband=True)

sol 0073 / zcam03014
* subframed caltarget; no ROIs; runs noninteractively

sol 0084 / zcam03134
* relatively boring case; has two separate 
 observations in input directory with distinct sequence ids;
 uncompressed, no partials, 4 ROIs; 
* test attempts to select second sequence in directory and pick the first option on everything

sol 0086 / zcam03135: 
* multiple observations in input directory with mixed version numbers; uncompressed, 6 ROIs, no partials
* test runs with noninteractive flag

sol 0106 / zcam03153:
  * single observation, second frame of mosaic, uses a .sel file, JPEG-compressed
  * runs with noninteractive flag

sol 0106_le
* as above but with all right-eye filters deleted

sol 0130 / zcam03175
* one observation in directory; MSSS_LOSSLESS compression
* test picks the first option on everything

130_missing_filters
* same as above, but filters L3, L5, and R2 are deleted
