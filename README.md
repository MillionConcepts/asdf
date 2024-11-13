# asdf -- [a]utomated [s]pectral [d]ata [f]unction

`asdf` is a command-line utility that automates last-mile reductin of multispectral data and metadata into analysis- and archive-ready formats. When run in default mode, the function automatically finds and processes multispectral image data files, generating many views on the data: parameter maps, decorrelation stretches, "true"  and enhanced color images, etc. If the user provides a "region of interest" (ROI) file, `asdf` generates context images and graphs of spectra, and prompts the user for ROI descriptors / classifiers. Each executation of `asdf` produces an interchange file containing observational data and metadata in a CSV format that can be used for further analysis in other tools, including [MultiDEx](https://github.com/millionconcepts/multidex).

`asdf` is actively supporting data analysis and / or operations for Mastcam-Z (Mars 2020), Mastcam (MSL), and ChemCam (MSL) instruments.

We are sharing the `asdf` code because we believe in open and reproducible science. The contents of this library are provided under a permissive BSD 3-Clause License, which places very few restrictions on what you can do with it.

### Installation

`asdf` can be installed from a local copy of the source code contained in this repository. **We recommend and only officially support installation into a `conda` environment on Linux.**

From the base directory of this repository as your working directory, the commands to install this software in a Linux command line are as follows:
```
conda env create -f environment.yml -y
conda activate asdf
pip install .
```

`asdf` will probably work on Windows and Mac OSX.
* **Windows install note.** If installing on Windows, we recommend using Windows Subsystem for Linux (WSL).
* **OSX install note.** If on Mac OSX, you will need to comment out the `hugin` package from the `environment.yml` before generating a `conda` environment. This is becuase there is not currently a compatible `hugin` package for Mac OSX available on `conda`. This means that the mosaicking functions will not be available for your install; the rest of the features of the software will still perform as designed.

### Contributing

Thank you for interested in contributing to `asdf`. Please review our code of conduct before
contributing. [![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](docs/code_of_conduct.md)

If you have found a bug or you have a feature request, please file an issue. We will also review pull requests, but would probably prefer you start the conversation with us first, so we can expect your contributions and make sure they will be within scope.

If you are a member of the Mars 2020 Science Team, and the content of your request is potentially subject to public release restrictions in the Team Guidelines, please [email us directly](chase@millionconcepts.com).

---

This work was supported by the Mars 2020 and Mars Science Laboratory rover projects.