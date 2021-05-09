## to set up your islamorada account for ```conda``` (only needs to be run once)
```
mkdir -p ~/.conda/envs/
ln -s /scratch/asdf/vendor/conda/asdf ~/.conda/envs/asdf
conda init tcsh
```
```conda init tcsh``` will put out a bunch of output, which should look like this:

> no change     /opt/miniconda3/condabin/conda
> no change     /opt/miniconda3/bin/conda
> no change     /opt/miniconda3/bin/conda-env
> no change     /opt/miniconda3/bin/activate
> no change     /opt/miniconda3/bin/deactivate
> no change     /opt/miniconda3/etc/profile.d/conda.sh
> no change     /opt/miniconda3/etc/fish/conf.d/conda.fish
> no change     /opt/miniconda3/shell/condabin/Conda.psm1
> no change     /opt/miniconda3/shell/condabin/conda-hook.ps1
> no change     /opt/miniconda3/lib/python3.9/site-packages/xontrib/conda.xsh
> no change     /opt/miniconda3/etc/profile.d/conda.csh
> modified      /home/$YOUR_USERNAME/.tcshrc
>
> ==> For changes to take effect, close and re-open your current shell. <==

You can ignore all of this output. You don't need to close and re-open your shell, 
unless you were already in ```tcsh`` (islamorada's default shell is ```bash```).

## any time you want to get ready to run ```asdf```
```
tcsh
conda activate asdf
```

## to get to the ```asdf``` directory
```
cd /scratch/asdf
```

## to run ```asdf```
**Note: you must be in /scratch/asdf.**
```
python asdf.py $path_to_iof $optional_roi_file
```

## other important ```asdf``` options
--upload: upload thumbnails and metadata to shared Google Sheet
-o, --output: output rapidlooks, metadata, and ROI file to specified directory 
-- default is /scratch/asdf/output/$username/$sol

For a complete list of options, run ```python asdf.py --help```. 

## example of usage
```
python asdf.py /scratch/cal_wg/flight/products/0036/iof/ZL5_0036_0670134129_053IOF_N0031392ZCAM03107_1100LUC01.IMG examples/asdf.sel --upload
```

This command runs ```asdf``` on the specific group of IOFs in the 
/scratch/cal_wg/flight/products/0036/iof/ directory that contains 
ZL5_0036_0670134129_053IOF_N0031392ZCAM03107_1100LUC01.IMG, evaluates 
the .sel file at examples/asdf.sel on them, and uploads thumbnails, 
metadata, and backup data.