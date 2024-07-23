from typing import Union

Waypoints = list[dict[str, Union[str, dict]]]
"""
Type alias for a list of waypoints parsed from GeoJSON fetched from the M20
public waypoints server. The general form of each of the elements of this
list is:

{'type': 'Feature',
 'properties': {'RMC': '3_0',
  'site': 3,
  'drive': 0,
  'sol': 13,
  'easting': 4354494.086,
  'northing': 1093299.695,
  'elev_geoid': -2569.91,
  'elev_radii': -4253.47,
  'radius': 3391936.53,
  'lon': 77.45088572,
  'lat': 18.44462715,
  'roll': -1.1817,
  'pitch': -0.0251,
  'yaw': 130.8816,
  'yaw_rad': 2.2843,
  'tilt': 1.18,
  'dist_m': 0.0,
  'dist_total_m': 0.0,
  'dist_km': 0.0,
  'dist_mi': 0.0,
  'final': 'y',
  'Note': 'Site increment, no motion.',
  'images': [{'name': 'Panorama',
    'isPanoramic': True,
    'url': 'Layers/mosaics/N_LRGB_0012XRAS_0030000_CYL_S_AUTOGENJ01.jpg',
    'rows': '5466',
    'columns': '18585',
    'azmin': '0',
    'azmax': '360',
    'elmin': '-86.5958',
    'elmax': '19.2967',
    'elzero': '997.216'}]},
 'geometry': {'type': 'Point',
  'coordinates': [77.45088572, 18.44462715, -2569.91]}}
"""