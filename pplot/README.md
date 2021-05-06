# Pretty Plot

A utility for easily converting VNIR multispectral data from Mastcam-Z into a standardized, pretty plot for quick distribution of results. The tool accepts either `marslab`-formatted or `MERspect`-formatted specta files.

####Installation / setup
git clone git@github.com:MillionConcepts/pretty-plot.git
cd pretty-plot
conda env create -n pretty-plot --file environment.yml 
conda activate pretty-plot
pip install git+ssh://git@github.com/MillionConcepts/marslab.git@asdf-reorg

---
The contents of this notebook are provided by the Western Washington University Reflectance Lab (PI: M. Rice) and Million Concepts (C. Million, M. St. Clair) under a BSD 3-Clause License. You may do nearly anything that you want with this code. Questions can be sent to chase@millionconcepts.com

`MERTools`/`MERspect` is proprietary software (Arizona State University) for rover tactical operations made available on an as-needed basis.
