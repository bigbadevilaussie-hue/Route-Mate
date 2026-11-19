import unittest

from render.standalone_bridge import add_alternating_row_bands, add_component_highlight


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

    def test_production_renderer_row_bands_use_hole_grid_origin(self):
        svg = '<svg viewBox="20 20 100 100"><circle cx="60" cy="60" r="4"/></svg>'
        result = add_alternating_row_bands(svg, 3)
        self.assertIn('y="75"', result)
        self.assertLess(result.index('data-route-mate-row-band'), result.index('<circle'))

    def test_component_highlight_uses_selected_footprint_bounds(self):
        project = {
            "board": {"rows": 4, "cols": 6},
            "components": [{
                "id": "r1", "defId": "def-resistor",
                "boardPos": {"row": 1, "col": 1},
                "flexibleEndPos": {"row": 1, "col": 4},
            }],
        }
        svg = '<svg viewBox="20 20 200 200"></svg>'
        result = add_component_highlight(svg, project, "r1")
        self.assertIn('data-route-mate-highlight="1"', result)
        self.assertIn('x="73" y="73" width="124" height="34"', result)

    def test_no_component_highlight_leaves_production_svg_unchanged(self):
        svg = '<svg viewBox="20 20 100 100"></svg>'
        self.assertEqual(add_component_highlight(svg, {}, None), svg)

    def test_requires_valid_svg_viewbox(self):
        with self.assertRaisesRegex(ValueError, "viewBox"):
            add_alternating_row_bands("<svg></svg>", 2)

    def test_requires_positive_integer_row_count(self):
        svg = '<svg viewBox="20 20 100 100"></svg>'
        with self.assertRaisesRegex(ValueError, "positive integer"):
            add_alternating_row_bands(svg, 0)


if __name__ == "__main__":
    unittest.main()
