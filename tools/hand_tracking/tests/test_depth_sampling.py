import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from depth_sampling import sample_hand_depth, depth_to_camera_points, depth_palm_basis, blend_palm_basis


class DepthSamplingTests(unittest.TestCase):
    def test_background_and_holes_are_rejected(self):
        d = np.full((100, 100), 900, dtype=np.int16)
        points = np.tile([0.5, 0.5], (21, 1)).astype(float)
        points[4] = [0.2, 0.2]
        points[8] = [0.8, 0.8]
        d[18:23, 18:23] = 1400
        d[78:83, 78:83] = 0
        out = sample_hand_depth(d, points)
        self.assertEqual(out[0], 900)
        self.assertTrue(np.isnan(out[4]))
        self.assertTrue(np.isnan(out[8]))

    def test_missing_palm_refuses_depth(self):
        d = np.full((100, 100), 900, dtype=np.int16)
        points = np.tile([0.5, 0.5], (21, 1)).astype(float)
        points[[0, 5, 9, 13]] = [2, 2]
        self.assertTrue(np.isnan(sample_hand_depth(d, points)).all())

    def test_backprojection_uses_intrinsics_and_preserves_missing(self):
        points = np.tile([0.5, 0.5], (21, 1)).astype(float)
        points[1] = [0.6, 0.6]
        depth = np.full(21, 1000.0)
        depth[2] = np.nan
        world = depth_to_camera_points(points, depth, 640, 480, 640, 480, 320, 240)
        np.testing.assert_allclose(world[0], [0, 0, 1000])
        np.testing.assert_allclose(world[1], [100, 100, 1000])
        self.assertTrue(np.isnan(world[2]).all())

    def test_backprojection_requires_measured_intrinsics(self):
        with self.assertRaises(ValueError):
            depth_to_camera_points(np.zeros((21, 2)), np.ones(21), 640, 480, 0, 480, 320, 240)
    def test_palm_basis_requires_valid_depth(self):
        points = np.full((21, 2), [0.5, 0.5])
        points[0], points[9] = [0.5, 0.58], [0.5, 0.5]
        points[5], points[17] = [0.46, 0.5], [0.54, 0.5]
        image = np.full((100, 100), 1000, dtype=np.int16)
        basis = depth_palm_basis(image, points, (100.0, 100.0, 50.0, 50.0))
        self.assertIsNotNone(basis)
        np.testing.assert_allclose(np.cross(basis[0], basis[1]), basis[2])
        self.assertIsNotNone(blend_palm_basis(basis, basis))
        image[:] = 0
        self.assertIsNone(depth_palm_basis(image, points, (100.0, 100.0, 50.0, 50.0)))
        self.assertIsNone(depth_palm_basis(image, None, (100.0, 100.0, 50.0, 50.0)))
        self.assertIs(blend_palm_basis(basis, None), basis)
    def test_invalid_shapes_rejected(self):
        with self.assertRaises(ValueError):
            sample_hand_depth(np.zeros((10, 10)), np.zeros((20, 2)))


if __name__ == '__main__':
    unittest.main()
