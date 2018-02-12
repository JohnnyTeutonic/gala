import numpy as np
from gala.viz import show_multiple_images


def test_value_error_multiple_o():
    TEST_IM_1 = np.random.randn(30, 30)
    TEST_IM_2 = np.random.randn(30, 30)
    show_multiple_images(TEST_IM_1, TEST_IM_2, image_type='colour')
