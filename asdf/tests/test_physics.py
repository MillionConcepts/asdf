from math import isclose
import asdf.physics


class TestAddDerivedIlluminationGeometry:
    def test_add_derived_illumination_geometry_1(self):
        metadata = {
            "SOLAR_ELEVATION": 5,
            "SOLAR_AZIMUTH": 10,
            "INSTRUMENT_ELEVATION": 15,
            "INSTRUMENT_AZIMUTH": 20,
        }
        metadata = asdf.physics.add_derived_illumination_geometry(metadata)
        assert metadata["SOLAR_ELEVATION"] == 5
        assert metadata["SOLAR_AZIMUTH"] == 10
        assert metadata["INSTRUMENT_ELEVATION"] == 15
        assert metadata["INSTRUMENT_AZIMUTH"] == 20
        assert metadata["INCIDENCE_ANGLE"] == 85
        assert metadata["INCIDENCE_AZIMUTH"] == 10
        assert metadata["EMISSION_ANGLE"] == 105
        assert metadata["EMISSION_AZIMUTH"] == 200
        assert isclose(metadata["PHASE_ANGLE"], 165.974748, abs_tol=0.000001)
