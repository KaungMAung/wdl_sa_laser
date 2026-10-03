from __future__ import annotations
from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QFormLayout,QFrame,QHBoxLayout,QHeaderView,QLabel,QLineEdit,QMessageBox,QPushButton,QSpinBox,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget
from ui.api_workers import ApiWorker

class RecipePage(QWidget):
    def __init__(self, service, actor=None, auth_service=None, parent=None):
        super().__init__(parent); self.service=service; self.api_mode=hasattr(service, "recipes"); self.actor=actor; self.auth_service=auth_service; self.editing_id=None; self._threads=set(); self._build_ui(); self.refresh()
    def _request(self, operation, success, failure=None):
        thread=QThread(self); worker=ApiWorker(operation); worker.moveToThread(thread); thread.started.connect(worker.run); worker.succeeded.connect(success); worker.failed.connect(failure or (lambda message: QMessageBox.warning(self,"Recipe Mapping",message))); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater); thread.finished.connect(thread.deleteLater); thread.finished.connect(lambda: self._threads.discard(thread)); self._threads.add(thread); thread.start()
    def _build_ui(self):
        root=QVBoxLayout(self); root.setContentsMargins(24,18,24,18); root.setSpacing(12)
        title=QLabel("EDIT RECIPE"); title.setObjectName("sectionTitle"); root.addWidget(title)
        card=QFrame(); card.setObjectName("recipeCard"); form=QFormLayout(card); form.setContentsMargins(16,12,16,12)
        self.material=QLineEdit(); self.polisher=QLineEdit(); self.engraver=QLineEdit(); self.name=QLineEdit(); self.carrier=QLineEdit(); self.prod_name=QLineEdit(); self.engraved_name=QLineEdit()
        form.addRow("MATERIAL NO. *",self.material); form.addRow("POLISHER RECIPE ID",self.polisher); form.addRow("ENGRAVER RECIPE ID",self.engraver); form.addRow("RECIPE NAME",self.name); form.addRow("CARRIER TYPE",self.carrier); form.addRow("PROD NAME",self.prod_name); form.addRow("ENGRAVED NAME",self.engraved_name)
        buttons=QHBoxLayout(); self.save=QPushButton("SAVE"); self.save.setObjectName("primaryButton"); self.cancel=QPushButton("CANCEL"); buttons.addWidget(self.save); buttons.addWidget(self.cancel); buttons.addStretch(1); form.addRow("",buttons); root.addWidget(card)
        search=QHBoxLayout(); search.addWidget(QLabel("SEARCH")); self.search=QLineEdit(); self.search.setPlaceholderText("Material No., Polisher/Engraver ID, Name, Carrier"); search.addWidget(self.search,1); add=QPushButton("+ ADD RECIPE"); add.clicked.connect(self.clear_form); search.addWidget(add); root.addLayout(search)
        self.table=QTableWidget(0,9); self.table.setHorizontalHeaderLabels(["No.","Material No.","Polisher Recipe ID","Engraver Recipe ID","Recipe Name","Carrier Type","ProdName","EngravedName","Actions"]); self.table.verticalHeader().setVisible(False); self.table.setSortingEnabled(True)
        h=self.table.horizontalHeader(); h.setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents); h.setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch); h.setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents); h.setSectionResizeMode(3,QHeaderView.ResizeMode.ResizeToContents); h.setSectionResizeMode(4,QHeaderView.ResizeMode.Stretch); h.setSectionResizeMode(5,QHeaderView.ResizeMode.ResizeToContents); h.setSectionResizeMode(6,QHeaderView.ResizeMode.Stretch); h.setSectionResizeMode(7,QHeaderView.ResizeMode.Stretch); h.setSectionResizeMode(8,QHeaderView.ResizeMode.ResizeToContents); root.addWidget(self.table,1)
        self.message=QLabel(); self.message.setObjectName("recipeMessage"); root.addWidget(self.message)
        self.save.clicked.connect(self.save_row); self.cancel.clicked.connect(self.clear_form); self.search.textChanged.connect(self.refresh)
    def refresh(self):
        if not hasattr(self,"table"): return
        self.table.setSortingEnabled(False); self.table.setRowCount(0)
        if self.api_mode:
            self._request(lambda: self.service.recipes(self.search.text()), self._populate)
            return
        rows = self.service.list(self.search.text())
        self._populate(rows)
    def _populate(self, rows):
        for number,row in enumerate(rows,1):
            i=self.table.rowCount(); self.table.insertRow(i)
            vals=(number,row["material_no"],row.get("polisher_recipe_id") or "",row.get("engraver_recipe_id") or "",row.get("recipe_name") or "",row.get("carrier_type") or "",row.get("prod_name") or "",row.get("engraved_name") or "")
            for c,v in enumerate(vals):
                item=QTableWidgetItem(str(v)); item.setTextAlignment(Qt.AlignmentFlag.AlignCenter if c in (0,2,3) else Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter); self.table.setItem(i,c,item)
            w=QWidget(); box=QHBoxLayout(w); box.setContentsMargins(4,2,4,2); edit=QPushButton("Edit"); delete=QPushButton("Delete"); box.addWidget(edit); box.addWidget(delete); edit.clicked.connect(lambda _,x=row["id"]: self.edit(x)); delete.clicked.connect(lambda _,x=row["id"],m=row["material_no"]: self.remove(x,m)); self.table.setCellWidget(i,8,w)
        self.table.setSortingEnabled(True)
    def save_row(self):
        try:
            payload = {
                "material": self.material.text(),
                "polisher": self.polisher.text(),
                "engraver": self.engraver.text(),
                "name": self.name.text(),
                "carrier": self.carrier.text(),
                "prod_name": self.prod_name.text(),
                "engraved_name": self.engraved_name.text(),
            }
            api_payload = {"material_no": payload["material"], "polisher_recipe_id": payload["polisher"] or None, "engraver_recipe_id": payload["engraver"] or None, "recipe_name": payload["name"], "carrier_type": payload["carrier"], "prod_name": payload["prod_name"], "engraved_name": payload["engraved_name"]}
            if self.api_mode:
                operation = (lambda: self.service.create_recipe(api_payload)) if self.editing_id is None else (lambda: self.service.update_recipe(self.editing_id, api_payload))
                self._request(operation, lambda row: (self.clear_form(), self.refresh(), self.message.setText("Recipe mapping saved")))
                return
            elif self.editing_id is None: row=self.service.create(**payload); action="recipe_created"
            else: row=self.service.update(self.editing_id, **payload); action="recipe_updated"
            if self.actor and self.auth_service and not self.api_mode: self.auth_service.audit(self.actor["username"], action, row["material_no"])
            self.clear_form(); self.refresh(); self.message.setText("Recipe mapping saved")
        except Exception as error: QMessageBox.warning(self,"Recipe Mapping",str(error))
    def edit(self,row_id):
        if self.api_mode:
            self._request(lambda: self.service.recipe(row_id), lambda row: self._load_row(row, row_id)); return
        row=self.service.get(row_id); self._load_row(row,row_id)
    def _load_row(self,row,row_id):
        if not row:return
        self.editing_id=row_id; self.material.setText(row["material_no"]); self.polisher.setText(str(row.get("polisher_recipe_id") or "")); self.engraver.setText(str(row.get("engraver_recipe_id") or "")); self.name.setText(row.get("recipe_name") or ""); self.carrier.setText(row.get("carrier_type") or ""); self.prod_name.setText(row.get("prod_name") or ""); self.engraved_name.setText(row.get("engraved_name") or ""); self.material.setFocus()
    def remove(self,row_id,material):
        if QMessageBox.question(self,"Delete Recipe",f"Delete recipe mapping for Material No. {material}?",QMessageBox.StandardButton.Cancel|QMessageBox.StandardButton.Yes,QMessageBox.StandardButton.Cancel)==QMessageBox.StandardButton.Yes:
            if self.api_mode:
                self._request(lambda: self.service.delete_recipe(row_id), lambda _: (self.refresh(), self.message.setText("Recipe mapping deleted"))); return
            self.service.delete(row_id)
            if self.actor and self.auth_service and not self.api_mode: self.auth_service.audit(self.actor["username"], "recipe_deleted", material)
            self.refresh(); self.message.setText("Recipe mapping deleted")
    def clear_form(self):
        self.editing_id=None; self.material.clear(); self.polisher.clear(); self.engraver.clear(); self.name.clear(); self.carrier.clear(); self.prod_name.clear(); self.engraved_name.clear(); self.save.setText("SAVE")
