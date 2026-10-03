import logging
from typing import Any

import pyodbc
from services.config_service import DatabaseConfig


LOGGER = logging.getLogger(__name__)


RUN_LOOKUP_SQL = """
SELECT TOP (15)
    ProdName AS [Product ID],
    MaterialNbr AS [Material No.],
    PO_Nbr AS [Run No.],
    DIAMOND_LOT_NUM AS [Diamond Lot Code],
    BatchNbr AS [Serial No.]
FROM
    [workflow-u-woodlands-sg-new].dbo.SA_MICRecord
WHERE
    PO_Nbr = ?
ORDER BY
    BatchNbr;
"""


class DatabaseService:
    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config

    def fetch_run_rows(self, po_number: str) -> list[Any]:
        LOGGER.info("Run No. lookup: %s", po_number)
        with pyodbc.connect(
            self.config.connection_string,
            timeout=self.config.connection_timeout,
        ) as connection:
            cursor = connection.cursor()
            cursor.execute(RUN_LOOKUP_SQL, po_number)
            rows = cursor.fetchall()
        LOGGER.info("Run No. %s returned %d record(s)", po_number, len(rows))
        return rows

    def test_connection(self) -> None:
        with pyodbc.connect(
            self.config.connection_string,
            timeout=self.config.connection_timeout,
        ) as connection:
            connection.cursor().execute("SELECT 1").fetchone()

