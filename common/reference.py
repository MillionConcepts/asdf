# Tables and utility functions for reference data

# Map mineral types to canonical lab spectra as defined by the Mastcam-Z team

LP = "data/zcam/lab/"

lab_spectra = {
    "Water Ice": {
        "Water Ice": LP + "Ice_WaterIce_WS08_HOSERLab.csv",
    },
    "Perchlorates": {
        "Fe Perchlorate": LP + "Perchlor_FePerchlorate_PRC002_HOSERLab.csv",
        "Mg Perchlorate": LP + "Perchlor_MgPerchlorate_PRC003_HOSERLab.csv",
    },
    "Sulfates": {
        "Pyrite": LP + "Sulfate_Pyrite_GDS483.c_USGS.csv",
        "Pyrrhotite": LP + "Sulfate_Pyrrhotite_HS269.3B_USGS.csv",
        "Ferrihydrite": LP + "Sulfate_Ferrihydrite_GDS75_USGS.csv",
        "Szomolnokite": LP + "Sulfate_Szomolnokite_SPT144_HOSERLab.csv",
        "Rozenite": LP + "Sulfate_Rozenite_casf58_RELAB.csv",
        "Jarosite": LP + "Sulfate_Jarosite_Natro9_McCollom_Ehlmann.csv",
        "Schwertmannite": LP + "Sulfate_Schwertmannite_BZ93-1_USGS.csv",
        "Copiapite": LP + "Sulfate_Copiapite_GDS21_USGS.csv",
        "Fe3+SO4(OH)": LP + "Sulfate_Fe3+SO4(OH)_c1sf18_RELAB.csv",
        "Ferricopiapite": LP + "Sulfate_Ferricopiapite_lasf39a_RELAB.csv",
        "Coquimbite": LP + "Sulfate_Coquimbite_GDS22_USGS.csv",
        "Melanterite": LP + "Sulfate_Melanterite_casf44_RELAB.csv",
        "Kieserite": LP + "Sulfate_Kieserite_KIEDE1.a.coarse_USGS.csv",
        "Rhomboclase": LP + "Sulfate_Rhomboclase_SPT139_HOSERLab.csv",
        "Alunite": LP + "Sulfate_Alunite_Natro6_McCollom_Ehlmann.csv",
        "Bassanite": LP + "Sulfate_Bassanite_GDS145_USGS.csv",
        "Epsomite": LP + "Sulfate_Epsomite_GDS149_USGS.csv",
        "Hexahydrite": LP + "Sulfate_Hexahydrite_SPT142_HOSERLab.csv",
        "Anydrite": LP + "Sulfate_Anhydrite_GDS42_USGS.csv",
        "Starkeyite": LP + "Sulfate_Starkeyite_starkeyi_Crowley.csv",
        "Gypsum": LP + "Sulfate_Gypsum_HS333.3B_USGS.csv",
    },
    "Olivines": {
        "Olivine (Fo1)": LP + "OLV_Fo1_c1po58_RELAB.csv",
        "Olivine (Fo66)": LP + "OLV_Fo66_ki3054-16849_USGS.csv",
        "Olivine (Fo90)": LP + "OLV_Fo90_c1po50_RELAB.csv",
        "Olivine (Fo97)": LP + "OLV_Fo97_c1po52_RELAB.csv",
    },
    "Chlorides": {
        "Antarcticite": LP + "Chloride_Antarcticite_Crowley.csv",
        "Carnallite": LP + "Chloride_Carnallite_NMNH98011_Crowley.csv",
        "Kainite": LP + "Chloride_Kainite_NMNH83904_Crowley.csv",
        "Bischofite": LP + "Chloride_Bischofite_Crowley.csv",
        "Sinjarite": LP + "Chloride_Sinjarite_Crowley.csv",
    },
    "Carbonates": {
        "Dolomite": LP + "CARB_Dolomite_HS102-3B_USGS.csv",
        "Magnesite": LP
        + "CARB_Magnesite_45-63um_EhlmannEtAl2011LPSCinPrep.csv",
        "Hydromagnesite": LP + "CARB_Hydromagnesite-cacb49_HOSERLab.csv",
        "Siderite": LP + "CARB_Siderite_HS271-3B_USGS.csv",
        "Calcite": LP + "CARB_Calcite_WS272_USGS.csv",
    },
    "Pyroxenes": {
        "Pigeonite": LP
        + "Pyx_Pigeonite_PYX112_En64.8_Fs26.9_Wo8.3_45-90microns_HOSERLab.csv",
        "Augite": LP
        + "Pyx_Augite_PYX016_En48.6_Fs2.5_Wo48.9_45-90microns_HOSERLab.csv",
        "Enstatite": LP
        + "Pyx_Enstatite_PYX070_En99.1_Fs0.1_Wo0.8_45-90microns_HOSERLab.csv",
        "Ferrosilite": LP
        + "Pyx_Ferrosilite_PYX117_En75_Fs25_Wo0_RELAB.csv",
        "Hedenbergite": LP
        + "Pyx_Hedenbergite_PYX010_En30.4_Fs18.7_Wo50.9_45-90microns_RELAB.csv",
        "Diopside": LP
        + "Pyx_Diopside_PYX036_En43.3_Fs13.4_Wo43.3_45-90microns_RELAB.csv",
    },
    "Amorphous": {
        "Obsidian Glass": LP + "amph_obsidian_glass_GS-CMP-015_RELAB.csv",
        "Nanophase Hematite": LP
        + "Amph_Nanophase_Hematite_s6fn18_Morris.csv",
        "JSC1": LP + "Amph_JSC1_Johnson.csv",
        "Basaltic Glass": LP
        + "amph_basaltic_glass_MUOinterior_Minitti2007.csv",
        "Tektite Glass": LP + "amph_tektite_glass_tek001_HOSERlab.csv",
    },
    "Oxides": {
        "MnO Ore": LP + "Oxide_MnO_ore_OREAS170A00000_Hardgrove.csv",
        "Magnetite": LP + "Oxide_Magnetite_hs195.13178_USGS.csv",
        "Maghemite": LP + "Oxide_Maghemite_gds81.13124_USGS.csv",
        "Akaganeite": LP + "Oxide_akaganeite_jb-cmp-048_c1jb48_RELAB.csv",
        "Ilmenite": LP + "Oxide_Ilmenite_hs231.11099_USGS.csv",
        "Goethite": LP + "Oxide_Goethite_ws222.8447_USGS.csv",
        "Hemtatite": LP + "Oxide_Hematite_gds27.9282_USGS.csv",
    },
    "Phillosilicates": {
        "NG1": LP + "Phyllo_NG1_45_75_bidir_EhlmannEtAl2011LPSCInPrep.csv",
        "Saponite": LP + "Phyllo_Saponite_SapCa-1_USGS.csv",
        "Kaolinite": LP + "Phyllo_Kaolinite_KGa-1wxyl_USGS.csv",
        "Glauconite": LP + "Phyllo_Glauconite_HS313.3B_USGS.csv",
        "Montmorillonite": LP + "Phyllo_Montmorillonite_SWy-1_USGS.csv",
        "Lizardite": LP + "Phyllo_Lizardite_NMNHR4687-b-165_USGS.csv",
        "Celadonite": LP + "Phyllo_Celadonite_Cel101_HOSERLab.csv",
        "Chlorite": LP + "Phyllo_Chlorite_LACL14_RELAB.csv",
        "Illite": LP + "Phyllo_Illite_IMt-1-b-lt2um_USGS.csv",
        "Actinolite": LP + "Phyllo_Actinolite_NMNHR16485_USGS.csv",
    },
    "Hydrosilicates": {
        "Epidote": LP + "HydSil_Epidote_GDS26-a_75-200um_USGS.csv",
        "Prehnite": LP + "HydSil_Prehnite_LAZE03_RELAB.csv",
        "Pumpellyite": LP
        + "HydSil_Pumpellyite-purityUnknown_LAZE02_RELAB.csv",
        "Analcime": LP + "HydSil_Analcime_GDS1_USGS.csv",
        "Talc": LP + "HydSil_Talc-GDS23_74-250um_USGS.csv",
    },
    "Feldspars": {
        "Maskelynite": LP + "FELD_Maskelynite_LALS91.csv",
        "Plagioclase 1": LP + "FELD_Plagioclase LAPL38.csv",
        "Plagioclase 2": LP + "FELD_Plagioclase_NCLS04_USGS.csv",
    },
}
