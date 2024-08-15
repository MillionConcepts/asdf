"""
functions that instantiate ideas about physical relations, i.e., photometry as
such, not just logical operations on pixels
"""

import numpy as np


def calculate_phase_angle(
    emission_angle, emission_azimuth, incidence_angle, incidence_azimuth
):
    """
    Calculate phase angle from emission and incidence angle (magnitude) and
    azimuth.
    """
    # angle between the projection of the incidence vector and the emission
    # vector on the surface
    delta_phi = abs(
        np.radians(incidence_azimuth) - np.radians(emission_azimuth)
    )
    # just converting to radians for neatness in subsequent expression
    theta_i = np.radians(incidence_angle)
    theta_e = np.radians(emission_angle)
    cos_phase = np.cos(theta_i) * np.cos(theta_e) + np.sin(theta_i) * np.sin(
        theta_e
    ) * np.cos(delta_phi)
    phase_angle = np.degrees(np.arccos(cos_phase))
    return phase_angle


def add_derived_illumination_geometry(metadata):
    """
    derive canonical incidence, emission, and phase angles from other metadata
    fields. see Shepherd et al. 2008, Rice et al. 2020, Rice 2021 (p.comm.)
    """
    incidence_angle = 90 - metadata["SOLAR_ELEVATION"]
    emission_angle = metadata["INSTRUMENT_ELEVATION"] + 90
    incidence_azimuth = metadata["SOLAR_AZIMUTH"]
    emission_azimuth = metadata["INSTRUMENT_AZIMUTH"] + 180
    phase_angle = calculate_phase_angle(
        emission_angle, emission_azimuth, incidence_angle, incidence_azimuth
    )
    for field, variable in zip(
        [
            "INCIDENCE_ANGLE",
            "INCIDENCE_AZIMUTH",
            "EMISSION_ANGLE",
            "EMISSION_AZIMUTH",
            "PHASE_ANGLE",
        ],
        [
            incidence_angle,
            incidence_azimuth,
            emission_angle,
            emission_azimuth,
            phase_angle,
        ],
    ):
        metadata[field] = variable
    return metadata
