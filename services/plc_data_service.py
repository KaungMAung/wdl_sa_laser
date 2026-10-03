import logging
from typing import Any
from dataclasses import replace

from models.tray_data import TrayData, TrayPartData
from services.config_service import PLCConfig
from services.recipe_service import RecipeService


LOGGER = logging.getLogger(__name__)

# PLC-owned outcome fields are read-only throughout this application.
READ_ONLY_PART_FIELDS = frozenset({"Result", "Status"})


class PLCRecipeError(RuntimeError):
    """Operator-facing recipe preparation failure while PLC remains reachable."""


def map_plc_value(raw_value: Any, mapping: dict[str, str]) -> str:
    """Map a raw PLC value without discarding it or failing on unknown values."""
    keys = [str(raw_value).strip()]
    # pycomm3 returns BOOL members as Python bool values. Also try the
    # corresponding 0/1 representation so the same configured mapping works
    # for BOOL and integer PLC fields.
    if isinstance(raw_value, bool):
        keys.append("1" if raw_value else "0")
    for key in keys:
        if key in mapping:
            return mapping[key]
    return f"UNKNOWN ({raw_value})"


class PLCDataService:
    """Single backend for PLC connection, tray writes, reads, and polling."""

    def __init__(self, config: PLCConfig, recipe_service: RecipeService) -> None:
        self.config = config
        self.recipe_service = recipe_service

    def check_connection(self) -> bool:
        from pycomm3 import LogixDriver

        with LogixDriver(self.config.ip_address, init_tags=False) as plc:
            return bool(plc.connected)

    def write_tray_data(
        self,
        writes: dict[str, Any],
        material_no: str,
        polisher_recipe_id: int,
        engraver_recipe_id: int,
    ) -> list[TrayData]:
        """Prepare the selected PLC recipe, then write/read TRAYDATA in one session."""
        from pycomm3 import LogixDriver

        if not 1 <= polisher_recipe_id <= 16:
            raise PLCRecipeError("Polisher Recipe ID must be between 1 and 16.")
        if engraver_recipe_id <= 0:
            raise PLCRecipeError("Engraver Recipe ID must be a positive integer.")
        recipe_tag = f"RECIPE{polisher_recipe_id}"
        select_value = self.recipe_select_value(polisher_recipe_id)
        write_args = tuple((tag, value) for tag, value in writes.items())
        LOGGER.info(
            "PLC recipe preparation started: MaterialNo=%s PolisherRecipeID=%d "
            "EngraverRecipeID=%d RecipeTag=%s SelectExpected=%d",
            material_no, polisher_recipe_id, engraver_recipe_id,
            recipe_tag, select_value,
        )
        with LogixDriver(self.config.ip_address) as plc:
            recipe = plc.read(recipe_tag)
            if getattr(recipe, "error", None):
                raise PLCRecipeError(f"PLC recipe {recipe_tag} is not available.")

            recipe_id_result = plc.read(f"{recipe_tag}.ID")
            if getattr(recipe_id_result, "error", None):
                raise PLCRecipeError(f"PLC recipe {recipe_tag} is not available.")
            actual_recipe_id = recipe_id_result.value
            LOGGER.info("PLC recipe ID read: Tag=%s.ID Expected=%d Actual=%r", recipe_tag, polisher_recipe_id, actual_recipe_id)
            if actual_recipe_id != polisher_recipe_id:
                raise PLCRecipeError(
                    "Recipe ID mismatch.\n"
                    f"Expected {recipe_tag}.ID = {polisher_recipe_id}\n"
                    f"Actual value = {actual_recipe_id}"
                )

            laser_tag = f"{recipe_tag}.LaserProgramNo"
            laser_write = plc.write((laser_tag, engraver_recipe_id))
            if getattr(laser_write, "error", None):
                raise PLCRecipeError(f"Unable to write {laser_tag}: {laser_write.error}")
            laser_read = plc.read(laser_tag)
            actual_laser = getattr(laser_read, "value", None)
            LOGGER.info("PLC LaserProgramNo verification: Tag=%s Written=%d Read=%r", laser_tag, engraver_recipe_id, actual_laser)
            if getattr(laser_read, "error", None) or actual_laser != engraver_recipe_id:
                raise PLCRecipeError(
                    f"Failed to verify Engraver Recipe ID in {laser_tag}."
                )

            select_tag = "HMI_RECIPE_SELECT_BIT"
            select_write = plc.write((select_tag, select_value))
            if getattr(select_write, "error", None):
                raise PLCRecipeError(
                    f"Unable to write {select_tag}: {select_write.error}"
                )
            select_read = plc.read(select_tag)
            actual_select = getattr(select_read, "value", None)
            LOGGER.info("PLC recipe select verification: Tag=%s Expected=%d Read=%r", select_tag, select_value, actual_select)
            if getattr(select_read, "error", None) or actual_select != select_value:
                raise PLCRecipeError("Failed to verify PLC recipe selection.")

            results = plc.write(*write_args)
            result_list = (
                list(results) if isinstance(results, (list, tuple)) else [results]
            )
            if len(result_list) != len(write_args):
                raise RuntimeError("PLC returned an unexpected number of write results")
            for requested_tag, result in zip(
                (tag for tag, _ in write_args), result_list, strict=True
            ):
                if getattr(result, "error", None):
                    raise RuntimeError(
                        f"Unable to write {requested_tag}: {result.error}"
                    )

            tray_values = self._read_tag_values_from_plc(plc, self._full_tag_names())
            trays = self._build_trays_from_values(tray_values)
        LOGGER.info(
            "PLC LOAD DATA completed: MaterialNo=%s RecipeTag=%s "
            "LaserProgramNo=%d HMI_RECIPE_SELECT_BIT=%d TRAYDATAWrites=%d",
            material_no, recipe_tag, engraver_recipe_id, select_value, len(writes),
        )
        return trays

    @staticmethod
    def recipe_select_value(polisher_recipe_id: int) -> int:
        raw_value = 1 << (polisher_recipe_id - 1)
        return raw_value - 65536 if raw_value >= 32768 else raw_value

    def poll_result_status(self, current_trays: list[TrayData]) -> tuple[list[TrayData], dict[tuple[int, int], dict[str, str]]]:
        values = self._read_tag_values(self._process_tag_names())
        self._log_process_values(values)
        identities = self._identity_values(values)
        return self._apply_process_values(current_trays, values, identities), identities

    @staticmethod
    def _identity_values(values: dict[str, Any]) -> dict[tuple[int, int], dict[str, str]]:
        observed = {}
        for tray_index in range(8):
            prefix = f"TRAYDATA[{tray_index}]"
            for part_number in range(1, 8):
                part_prefix = f"{prefix}.Part[{part_number}]"
                observed[(tray_index, part_number - 1)] = {
                    "serial_no": str(values[f"{part_prefix}.SerialNo"] or "").strip(),
                    "material_no": str(values[f"{prefix}.MaterialNo"] or "").strip(),
                    "diamond_lot_code": str(values[f"{prefix}.LotCode"] or "").strip(),
                }
        return observed

    def _log_process_values(self, values: dict[str, Any]) -> None:
        entries: list[str] = []
        for tray_index in range(8):
            for part_number in range(1, 8):
                prefix = f"TRAYDATA[{tray_index}].Part[{part_number}]"
                raw_result = values[f"{prefix}.Result"]
                raw_status = values[f"{prefix}.Status"]
                result_text = map_plc_value(raw_result, self.config.result_mapping)
                status_text = map_plc_value(raw_status, self.config.status_mapping)
                entries.append(
                    f"{prefix}: Result={raw_result!r}/{result_text}, "
                    f"Status={raw_status!r}/{status_text}"
                )
        LOGGER.info("PLC Result/Status poll: %s", "; ".join(entries))

    def _read_real_tray_data(self) -> list[TrayData]:
        values = self._read_tag_values(self._full_tag_names())
        return self._build_trays_from_values(values)

    def _read_tag_values(self, tags: list[str]) -> dict[str, Any]:
        from pycomm3 import LogixDriver

        with LogixDriver(
            self.config.ip_address,
            tag_namespace_filter="TRAYDATA",
        ) as plc:
            return self._read_tag_values_from_plc(plc, tags)

    @staticmethod
    def _read_tag_values_from_plc(plc: Any, tags: list[str]) -> dict[str, Any]:
        results = plc.read(*tags)
        result_list = list(results) if isinstance(results, (list, tuple)) else [results]
        if len(result_list) != len(tags):
            raise RuntimeError("PLC returned an unexpected number of TRAYDATA values")

        values: dict[str, Any] = {}
        for requested_tag, result in zip(tags, result_list, strict=True):
            if getattr(result, "error", None):
                raise RuntimeError(f"Unable to read {requested_tag}: {result.error}")
            values[requested_tag] = result.value
        return values

    @staticmethod
    def _full_tag_names() -> list[str]:
        tags: list[str] = []
        for tray_index in range(8):
            prefix = f"TRAYDATA[{tray_index}]"
            tags.extend(
                [
                    f"{prefix}.Done",
                    f"{prefix}.RunNo",
                    f"{prefix}.ProductID",
                    f"{prefix}.LotCode",
                    f"{prefix}.MaterialNo",
                    f"{prefix}.NewTray",
                ]
            )
            for part_number in range(1, 8):
                part_prefix = f"{prefix}.Part[{part_number}]"
                tags.extend(
                    [
                        f"{part_prefix}.Result",
                        f"{part_prefix}.SerialNo",
                        f"{part_prefix}.Status",
                    ]
                )
        return tags

    @staticmethod
    def _process_tag_names() -> list[str]:
        tags: list[str] = []
        for tray_index in range(8):
            for part_number in range(1, 8):
                prefix = f"TRAYDATA[{tray_index}].Part[{part_number}]"
                tags.extend([f"{prefix}.Result", f"{prefix}.Status", f"{prefix}.SerialNo"])
            tags.extend([f"TRAYDATA[{tray_index}].MaterialNo", f"TRAYDATA[{tray_index}].LotCode"])
        return tags

    def _build_trays_from_values(self, values: dict[str, Any]) -> list[TrayData]:
        engraved_names = {
            material: (
                self.recipe_service.by_material(material) or {}
            ).get("engraved_name", "")
            for material in {
                str(values[f"TRAYDATA[{tray_index}].MaterialNo"] or "").strip()
                for tray_index in range(8)
            }
            if material
        }
        trays: list[TrayData] = []
        for tray_index in range(8):
            prefix = f"TRAYDATA[{tray_index}]"
            parts = tuple(
                self._part_from_values(values, prefix, part_number)
                for part_number in range(1, 8)
            )
            trays.append(
                TrayData(
                    tray_index=tray_index,
                    done=values[f"{prefix}.Done"],
                    run_no=values[f"{prefix}.RunNo"],
                    engraved_name=engraved_names.get(
                        str(values[f"{prefix}.MaterialNo"] or "").strip(), ""
                    ),
                    lot_code=values[f"{prefix}.LotCode"],
                    material_no=values[f"{prefix}.MaterialNo"],
                    new_tray=values[f"{prefix}.NewTray"],
                    parts=parts,
                )
            )
        return trays

    def _part_from_values(
        self, values: dict[str, Any], tray_prefix: str, part_number: int
    ) -> TrayPartData:
        prefix = f"{tray_prefix}.Part[{part_number}]"
        raw_result = values[f"{prefix}.Result"]
        raw_status = values[f"{prefix}.Status"]
        return TrayPartData(
            result=raw_result,
            serial_no=values[f"{prefix}.SerialNo"],
            status=raw_status,
            result_text=map_plc_value(raw_result, self.config.result_mapping),
            status_text=map_plc_value(raw_status, self.config.status_mapping),
        )

    def _apply_process_values(
        self,
        current_trays: list[TrayData],
        values: dict[str, Any],
        identities: dict[tuple[int, int], dict[str, str]],
    ) -> list[TrayData]:
        refreshed: list[TrayData] = []
        for tray in current_trays:
            parts: list[TrayPartData] = []
            for part_index, part in enumerate(tray.parts):
                part_number = part_index + 1
                prefix = f"TRAYDATA[{tray.tray_index}].Part[{part_number}]"
                raw_result = values[f"{prefix}.Result"]
                raw_status = values[f"{prefix}.Status"]
                identity = identities[(tray.tray_index, part_index)]
                mismatch = (
                    identity["serial_no"] != str(part.serial_no or "").strip()
                    or identity["material_no"] != str(tray.material_no or "").strip()
                    or identity["diamond_lot_code"] != str(tray.lot_code or "").strip()
                )
                if mismatch:
                    raw_result = part.result
                    raw_status = part.status
                    result_text = part.result_text
                    status_text = part.status_text
                else:
                    result_text = map_plc_value(raw_result, self.config.result_mapping)
                    status_text = map_plc_value(raw_status, self.config.status_mapping)
                parts.append(
                    replace(
                        part,
                        result=raw_result,
                        status=raw_status,
                        result_text=result_text,
                        status_text=status_text,
                        identity_mismatch=mismatch,
                    )
                )
            refreshed.append(replace(tray, parts=tuple(parts)))
        return refreshed
