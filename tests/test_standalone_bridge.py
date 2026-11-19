import unittest

from render.standalone_bridge import (\n    add_alternating_row_bands,\n    add_board_coordinate_labels,\n    add_component_highlight,\n)


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


    def test_coordinate_labels_follow_hole_centres_and_start_at_one(self):
        svg = '<svg viewBox="20 20 200 200"><text>Top · R0·C0</text></svg>'
        result = add_board_coordinate_labels(svg, 3, 4)
        self.assertIn('x="60" y="38"', result)
        self.assertIn('data-route-mate-column="1">1</text>', result)
        self.assertIn('x="150" y="38"', result)
        self.assertIn('data-route-mate-column="4">4</text>', result)
        self.assertIn('x="38" y="63"', result)
        self.assertIn('data-route-mate-row="1">1</text>', result)
        self.assertIn('data-route-mate-row="3">3</text>', result)
        self.assertNotIn("R0·C0", result)

    def test_copper_coordinate_labels_reverse_columns_for_mirrored_view(self):
        svg = '<svg viewBox="20 20 200 200"></svg>'
        result = add_board_coordinate_labels(svg, 2, 3, mirrored=True)
        self.assertIn('x="120" y="38"', result)
        self.assertIn('data-route-mate-column="1">1</text>', result)
        self.assertIn('x="60" y="38"', result)
        self.assertIn('data-route-mate-column="3">3</text>', result)

    def test_coordinate_labels_reject_invalid_dimensions(self):
        svg = '<svg viewBox="20 20 200 200"></svg>'
        with self.assertRaisesRegex(ValueError, "rows"):
            add_board_coordinate_labels(svg, 0, 3)
        with self.assertRaisesRegex(ValueError, "cols"):
            add_board_coordinate_labels(svg, 2, 0)

    def test_requires_valid_svg_viewbox(self):
        with self.assertRaisesRegex(ValueError, "viewBox"):
            add_alternating_row_bands("<svg></svg>", 2)

    def test_requires_positive_integer_row_count(self):
        svg = '<svg viewBox="20 20 100 100"></svg>'
        with self.assertRaisesRegex(ValueError, "positive integer"):
            add_alternating_row_bands(svg, 0)


if __name__ == "__main__":
    unittest.main()
