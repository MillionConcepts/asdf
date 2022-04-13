import matplotlib as mpl

from rapid.algebra import make_classifier_look
from rapid.helpers import get_zcam_bandset

mpl.rcParams['image.interpolation'] = None


image_path = '/home/michael/Desktop/zcam_data/products/0077/iof/'
roi_path = None
observation = get_zcam_bandset(image_path, roi_path)

BD866 = {'look': 'band_depth', 'bands': ('R1', 'R6', 'R2')}
BD910 = {'look': 'band_depth', 'bands': ('R1', 'R5', 'R3')}
BD939 = {'look': 'band_depth', 'bands': ('R1', 'R6', 'R4')}
BD978 = {'look': 'band_depth', 'bands': ('R1', 'R6', 'R5')}
R800_1022 = {'look': 'ratio', 'bands': ('R1', 'R6')}
R631_800 = {'look': 'ratio', 'bands': ('R0R', 'R1')}
R800_631 = {'look': 'ratio', 'bands': ('R1', 'R0R')}

# currently this implicitly places a boolean AND between
# each statement in a class-membership definition.
# if more sophisticated logic is desired, we can implement it.

# noinspection PyTypeChecker
spectral_class_definitions = {
    'hematite': {
        'conditions': (
            BD866 | {'range': (0.08, 0.2)},
            R800_631 | {'range': (1.2, 2.0)}
        ),
        'color': 'red'
    },
    'red_slope':  {
        'conditions': (
            R631_800 | {'range': (0.4, 0.8)},
            R800_1022 | {'range': (0.6, 0.9)}
        ),
        'color': 'teal'
    }
}

rclook = make_classifier_look(
    spectral_class_definitions,
    observation
)
class_arrays = rclook.execute()
