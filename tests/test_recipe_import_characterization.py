"""Characterization of Recipe.xlsx existing-row import behavior."""

from __future__ import annotations

import tempfile
import unittest
import gc
from pathlib import Path

import openpyxl

from services.recipe_service import RecipeService


def _workbook(path: Path, recipe_id: int, recipe_name: str) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet2"
    sheet.append(["Material_No", "Polisher_Rcp_Id", "Engraver_Rcp_Id", "Rcp_Name", "Carrier type"])
    sheet.append(["000123", recipe_id, 2, recipe_name, "CT"])
    book.save(path)


class RecipeImportCharacterizationTests(unittest.TestCase):
    def test_existing_row_is_reported_updated_but_values_are_not_updated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "Recipe.xlsx"
            database = root / "recipes.db"
            _workbook(workbook, 1, "INITIAL")
            service = RecipeService(database, workbook)
            inserted = service.by_material("000123")
            self.assertEqual(inserted["polisher_recipe_id"], 1)
            self.assertEqual(inserted["recipe_name"], "INITIAL")

            _workbook(workbook, 9, "CHANGED")
            with self.assertLogs("services.recipe_service", level="INFO") as captured:
                service.import_workbook()
            updated = service.by_material("000123")

            self.assertEqual(updated["polisher_recipe_id"], 1)
            self.assertEqual(updated["recipe_name"], "INITIAL")
            self.assertTrue(any("updated=1" in line for line in captured.output))
            # RecipeService does not retain the workbook, but openpyxl's
            # read-only workbook can hold a Windows file handle until GC.
            gc.collect()


if __name__ == "__main__":
    unittest.main()
