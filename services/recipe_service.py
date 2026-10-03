from __future__ import annotations
import logging, sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

LOGGER = logging.getLogger(__name__)
FIELDS = "id, material_no, polisher_recipe_id, engraver_recipe_id, recipe_name, carrier_type, prod_name, engraved_name, created_at, updated_at"

class RecipeValidationError(ValueError): pass
class RecipeConflictError(ValueError): pass

class RecipeService:
    def __init__(self, database_path: Path | None = None, workbook_path: Path | None = None) -> None:
        root = Path(__file__).resolve().parents[1]
        self.database_path = database_path or root / "data" / "lasermaker.db"
        self.workbook_path = workbook_path or root / "Recipe.xlsx"
        self.database_path.parent.mkdir(parents=True, exist_ok=True); self.initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.database_path, timeout=5); db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def initialize(self) -> None:
        with self._connect() as db:
            create_sql = """CREATE TABLE IF NOT EXISTS recipe_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT, material_no TEXT NOT NULL UNIQUE,
                polisher_recipe_id INTEGER, engraver_recipe_id INTEGER, recipe_name TEXT,
                carrier_type TEXT, prod_name TEXT, engraved_name TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"""
            db.execute(create_sql)
            columns = {r[1] for r in db.execute("PRAGMA table_info(recipe_mapping)")}
            if "recipe_id" in columns:
                # Migrate the earlier single-ID schema, including its NOT NULL
                # constraint, so new rows can leave either ID nullable.
                db.execute("ALTER TABLE recipe_mapping RENAME TO recipe_mapping_legacy")
                db.execute(create_sql)
                db.execute("""INSERT INTO recipe_mapping
                    (id, material_no, polisher_recipe_id, engraver_recipe_id,
                     recipe_name, carrier_type, prod_name, engraved_name,
                     created_at, updated_at)
                    SELECT id, material_no, recipe_id, NULL, recipe_name,
                           carrier_type, NULL, NULL, created_at, updated_at
                    FROM recipe_mapping_legacy""")
                db.execute("DROP TABLE recipe_mapping_legacy")
                columns = {r[1] for r in db.execute("PRAGMA table_info(recipe_mapping)")}
            for column in ("prod_name", "engraved_name"):
                if column not in columns:
                    db.execute(f"ALTER TABLE recipe_mapping ADD COLUMN {column} TEXT")
        self.import_workbook()

    @staticmethod
    def _header(value: Any) -> str: return "".join(str(value or "").strip().lower().replace("_", "").split())
    @staticmethod
    def _text(value: Any) -> str:
        if value is None: return ""
        if isinstance(value, float) and value.is_integer(): return str(int(value))
        return str(value).strip()
    @classmethod
    def _integer(cls, value: Any) -> int:
        number = float(cls._text(value))
        if not number.is_integer(): raise ValueError(value)
        return int(number)
    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None: return dict(row) if row else None

    def import_workbook(self) -> None:
        if not self.workbook_path.exists(): LOGGER.warning("Recipe workbook not found: %s", self.workbook_path); return
        try:
            import openpyxl
            book = openpyxl.load_workbook(self.workbook_path, read_only=True, data_only=True)
            if "Sheet2" not in book.sheetnames: LOGGER.warning("Recipe.xlsx has no Sheet2"); return
            rows = book["Sheet2"].iter_rows(values_only=True); headers = next(rows, None)
            indexes = {self._header(v): i for i, v in enumerate(headers or ())}
            material_key = next((k for k in indexes if k in {"materialnosku", "materialno", "materialnumber"}), None)
            polisher_key = next((k for k in indexes if k in {"recipe", "polisherrecipeid", "polisherrecipe", "polisherrcpid"}), None)
            engraver_key = next((k for k in indexes if k in {"engraverrecipeid", "engraverrecipe", "engraverrcpid"}), None)
            if not material_key or not polisher_key: raise ValueError(f"Missing Material/Recipe columns: {list(indexes)}")
            counts = [0, 0, 0, 0, 0]
            with self._connect() as db:
                for row in rows:
                    counts[0] += 1
                    try:
                        material = self._text(row[indexes[material_key]])
                        if not material: counts[3] += 1; continue
                        polisher = self._integer(row[indexes[polisher_key]]) if self._text(row[indexes[polisher_key]]) else None
                        engraver = self._integer(row[indexes[engraver_key]]) if engraver_key and self._text(row[indexes[engraver_key]]) else None
                        if (polisher is None or polisher <= 0) and (engraver is None or engraver <= 0):
                            counts[3] += 1
                            continue
                        name_key = next((k for k in ("recipename", "rcpname") if k in indexes), None)
                        name = self._text(row[indexes[name_key]]) if name_key else ""
                        carrier = self._text(row[indexes["carriertype"]]) if "carriertype" in indexes else ""
                        prod_name = self._text(row[indexes["prodname"]]) if "prodname" in indexes else ""
                        engraved_name = self._text(row[indexes["engravedname"]]) if "engravedname" in indexes else ""
                        old = db.execute("SELECT id FROM recipe_mapping WHERE material_no=?", (material,)).fetchone()
                        if old:
                            counts[2] += 1
                        else:
                            db.execute("INSERT INTO recipe_mapping (material_no, polisher_recipe_id, engraver_recipe_id, recipe_name, carrier_type, prod_name, engraved_name) VALUES (?, ?, ?, ?, ?, ?, ?)", (material, polisher, engraver, name or None, carrier or None, prod_name or None, engraved_name or None)); counts[1] += 1
                    except Exception: counts[4] += 1; LOGGER.exception("Recipe workbook row import failed")
            LOGGER.info("Recipe import Sheet2: rows=%d inserted=%d updated=%d skipped=%d errors=%d", *counts)
        except Exception: LOGGER.exception("Unable to import Recipe.xlsx")

    @classmethod
    def _validate(cls, material: Any, polisher: Any, engraver: Any) -> tuple[str, int | None, int | None]:
        material = cls._text(material)
        if not material: raise RecipeValidationError("Material No. cannot be blank")
        try: p = cls._integer(polisher) if cls._text(polisher) else None; e = cls._integer(engraver) if cls._text(engraver) else None
        except ValueError as error: raise RecipeValidationError("Recipe IDs must be positive integers") from error
        if (p is not None and p <= 0) or (e is not None and e <= 0) or (p is None and e is None): raise RecipeValidationError("At least one positive Recipe ID is required")
        return material, p, e

    def list(self, search: str = "") -> list[dict[str, Any]]:
        value = f"%{self._text(search)}%"
        with self._connect() as db: rows = db.execute(f"SELECT {FIELDS} FROM recipe_mapping WHERE material_no LIKE ? OR CAST(polisher_recipe_id AS TEXT) LIKE ? OR CAST(engraver_recipe_id AS TEXT) LIKE ? OR COALESCE(recipe_name,'') LIKE ? OR COALESCE(carrier_type,'') LIKE ? OR COALESCE(prod_name,'') LIKE ? OR COALESCE(engraved_name,'') LIKE ? ORDER BY material_no", (value,)*7).fetchall()
        return [dict(r) for r in rows]
    def get(self, row_id: int) -> dict[str, Any] | None:
        with self._connect() as db: return self._row(db.execute(f"SELECT {FIELDS} FROM recipe_mapping WHERE id=?", (int(row_id),)).fetchone())
    def by_material(self, material: str) -> dict[str, Any] | None:
        with self._connect() as db: return self._row(db.execute(f"SELECT {FIELDS} FROM recipe_mapping WHERE material_no=?", (self._text(material),)).fetchone())
    def create(self, material: Any, polisher: Any, engraver: Any, name: str = "", carrier: str = "", prod_name: str = "", engraved_name: str = "") -> dict[str, Any]:
        m,p,e = self._validate(material, polisher, engraver)
        try:
            with self._connect() as db: row_id = db.execute("INSERT INTO recipe_mapping (material_no, polisher_recipe_id, engraver_recipe_id, recipe_name, carrier_type, prod_name, engraved_name) VALUES (?, ?, ?, ?, ?, ?, ?)", (m,p,e,self._text(name) or None,self._text(carrier) or None,self._text(prod_name) or None,self._text(engraved_name) or None)).lastrowid
        except sqlite3.IntegrityError as error: raise RecipeConflictError(f"Material No. {m} already exists.") from error
        return self.get(row_id)  # type: ignore[return-value]
    def update(self, row_id: int, material: Any, polisher: Any, engraver: Any, name: str = "", carrier: str = "", prod_name: str = "", engraved_name: str = "") -> dict[str, Any]:
        m,p,e = self._validate(material, polisher, engraver)
        try:
            with self._connect() as db:
                result = db.execute(
                    """UPDATE recipe_mapping
                    SET material_no=?, polisher_recipe_id=?, engraver_recipe_id=?,
                        recipe_name=?, carrier_type=?, prod_name=?, engraved_name=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?""",
                    (
                        m, p, e, self._text(name) or None, self._text(carrier) or None,
                        self._text(prod_name) or None, self._text(engraved_name) or None,
                        int(row_id),
                    ),
                )
                if result.rowcount == 0: raise KeyError("Recipe mapping not found")
        except sqlite3.IntegrityError as error: raise RecipeConflictError(f"Material No. {m} already exists.") from error
        return self.get(row_id)  # type: ignore[return-value]
    def delete(self, row_id: int) -> bool:
        with self._connect() as db: return db.execute("DELETE FROM recipe_mapping WHERE id=?", (int(row_id),)).rowcount > 0
