Observational data files for test cases should go into this directory.

Current cases:

sol 0084 / zcam03134
* relatively boring case; has two separate 
 observations in input directory with distinct sequence ids;
 uncompressed, no partials, 4 ROIs; 
* test attempts to select second sequence in directory and pick the first option on everything

sol 0086 / zcam03135: 
* multiple observations in input directory with mixed version numbers; uncompressed, 6 ROIs, no partials
* test runs with noninteractive flag

sol 0130 / zcam03175
* one observation in directory; MSSS_LOSSLESS compression
* test runs with skip-rapidlooks flag and picks the first option
 on everything
