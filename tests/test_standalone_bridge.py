import unittest

from render.standalone_bridge import add_alternating_row_bands


class AlternatingRowBandTests(unittest.TestCase):
    def test_adds_odd_row_bands_inside_svg_viewbox(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="20 20 100 100"><circle cx="60" cy="60" r="4"/></svg>'
        result = add_alternating_row_bands(svg, 3)
        self.assertEqual(result.count('data-route-mate-row-band="1"'), 1)
        self.assertIn('x="20" y="75" width="100" height="30"', result)
        self.assertLess(result.index('data-route-mate-row-band'), result.index('<circle'))

    def test_two_rows_shades_only_the_alternating_row(self):
        svg = '<svg viewBox="20 20 100 100"><circle cx="60" cy="60" r="4"/></svg>'
        result = add_alternating_row_bands(svg, 2)
        self.assertEqual(result.count('data-route-mate-row-band="1"'), 1)
        self.assertIn('y="75"', result)

    def test_single_row_has_no_alternating_band(self):
        svg = '<svg viewBox="20 20 100 100"><circle cx="60" cy="60" r="4"/></svg>'
        self.assertNotIn('data-route-mate-row-band', add_alternating_row_bands(svg, 1))

    def test_requires_valid_svg_viewbox(self):
        with self.assertRaisesRegex(ValueError, "viewBox"):
            add_alternating_row_bands("<svg></svg>", 2)

    def test_requires_positive_integer_row_count(self):
        svg = '<svg viewBox="20 20 100 100"></svg>'
        with self.assertRaisesRegex(ValueError, "positive integer"):
            add_alternating_row_bands(svg, 0)


if __name__ == "__main__":
    unittest.main()
