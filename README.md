# asdf -- [a]rchive [s]pectra [d]ata [f]iles

A command-line script for generating archive-ready data and metadata that record
multispectral analysis workflows with Mastcam-Z.

---

## Overview

asdf automates last-mile reduction of Mastcam-Z (ZCAM) multispectral image data
from the Mars 2020 Perseverance rover. It is part of the
[marslab](https://github.com/MillionConcepts/marslab) suite of interoperable
tools for multispectral data analysis, which is in tactical use for Mastcam-Z
multispectral operations and has also been extensively applied to MSL Mastcam
data.

Given a set of Mastcam-Z IOF (radiance factor) image files, asdf automatically:

- generates browse products: parameter maps, decorrelation stretch (DCS) images,
  and "true" and enhanced color composites
- extracts spectral data and metadata and records them in a CSV interchange
  format compatible with other marslab tools (MultiDEx, VISOR)
- optionally evaluates a region-of-interest (ROI) file, generating context
  images and spectral plots for each ROI and prompting the user for ROI
  descriptors based on Mastcam-Z Multispectral Working Group (MSWG)
  classifications

asdf records analyses in archive-ready formats consistent with Planetary Data
System v4 policies. A secondary mode (`fdsa`) can regenerate previous analyses
with modified parameters, supporting calibration updates, refined ROI
selections, and quality assurance checks.

For a reprsentative sample of `asdf` outputs, please see [this archive](https://mabel.wwu.edu/do/5c19d020-619d-413a-99e0-3fdb376f6630).

## Basic usage

Point asdf at any single IOF image file from a Mastcam-Z observation:

```
python asdf.py /path/to/mastcamz_image.IMG
```

asdf will automatically find other image files from the same observation if they
are in the same directory. You may also pass a path to a directory, in which
case asdf will list available observation sequences and allow you to choose one (or all).

To include a region-of-interest file:

```
python asdf.py /path/to/mastcamz_image.IMG /path/to/roi_file.sel
```

The ROI file may be a MERspect `.sel` file or a `-roi.fits` file. Without a ROI
file, asdf generates browse products and a metadata-only CSV. (Sample `-roi.fits` files are [available here](https://mabel.wwu.edu/do/5c19d020-619d-413a-99e0-3fdb376f6630).)

For a full list of options:

```
python asdf.py --help
```

> **Note for Perseverance and Mastcam-Z team members:** Please refer to internal documentation for running `asdf` on project servers as part of mission and instrument operations support. The person who trained you for Mastcam-Z sPDL duties should provide this information; if they have not, please request it.

## Installation

asdf requires conda. To create the environment:

```
conda env create -f environment.yml
conda activate asdf
pip install -e .
```

> **macOS users:** Before creating the environment, comment out the `hugin`
> line in `environment.yml`. There is no matching conda package for macOS;
> mosaicking capabilities are not currently available on macOS.

---

The contents of this library are provided by the Western Washington University
Reflectance Lab (PI: M. Rice) and Million Concepts (C. Million, M. St. Clair)
under a BSD 3-Clause License. This license places very few restrictions on what
you can do with this code. This work was supported by the Mars Science Laboratory Participating Scientist Program and the Mars 2020 project.
