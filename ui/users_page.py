from PySide6.QtCore import QThread
from PySide6.QtWidgets import QComboBox,QDialog,QFormLayout,QHBoxLayout,QLabel,QLineEdit,QMessageBox,QPushButton,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget
from ui.api_workers import ApiWorker

ROLES = ("Admin", "Engineer", "Operator")

class UserDialog(QDialog):
    def __init__(self,parent=None,user=None,reset=False):
        super().__init__(parent); self.setWindowTitle("Reset Password" if reset else ("Edit User" if user else "Create User")); form=QFormLayout(self); self.username=QLineEdit(user["username"] if user else ""); self.password=QLineEdit(); self.password.setEchoMode(QLineEdit.EchoMode.Password); self.role=QComboBox(); self.role.addItems(ROLES); self.role.setCurrentText(user["role"] if user else "Operator");
        if not reset:form.addRow("Username *",self.username);form.addRow("Role *",self.role)
        if reset or not user:form.addRow("Password *",self.password)
        save=QPushButton("Save");save.clicked.connect(self.accept);form.addRow(save)

class UsersPage(QWidget):
    def __init__(self,service,actor,parent=None):
        super().__init__(parent);self.service=service;self.api_mode=hasattr(service,"users");self.actor=actor;self._threads=set();root=QVBoxLayout(self);title=QLabel("USER MANAGEMENT");title.setObjectName("sectionTitle");root.addWidget(title);add=QPushButton("+ CREATE USER");add.clicked.connect(self.create);root.addWidget(add);self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(["Username","Role","Status","Actions"]);root.addWidget(self.table);self.refresh()
    def _request(self, operation, success):
        thread=QThread(self); worker=ApiWorker(operation); worker.moveToThread(thread); thread.started.connect(worker.run); worker.succeeded.connect(success); worker.failed.connect(lambda message: QMessageBox.warning(self,"User Management",message)); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater); thread.finished.connect(thread.deleteLater); thread.finished.connect(lambda: self._threads.discard(thread)); self._threads.add(thread); thread.start()
    def refresh(self):
        self.table.setRowCount(0)
        if self.api_mode: self._request(self.service.users, self._populate); return
        rows = self.service.list_users(self.actor); self._populate(rows)
    def _populate(self, rows):
        for user in rows:
            r=self.table.rowCount();self.table.insertRow(r)
            for c,v in enumerate((user["username"],user["role"],"Active" if user["is_active"] else "Disabled")):self.table.setItem(r,c,QTableWidgetItem(v))
            w=QWidget();b=QHBoxLayout(w);b.setContentsMargins(2,2,2,2)
            for text,fn in (("Edit",lambda _,u=user:self.edit(u)),("Reset Password",lambda _,u=user:self.reset(u)),("Disable" if user["is_active"] else "Enable",lambda _,u=user:self.toggle(u))):q=QPushButton(text);q.clicked.connect(fn);b.addWidget(q)
            self.table.setCellWidget(r,3,w)
    def _error(self,fn):
        try:fn();self.refresh()
        except Exception as e:QMessageBox.warning(self,"User Management",str(e))
    def create(self):
        d=UserDialog(self)
        if d.exec():
            if self.api_mode: self._request(lambda:self.service.create_user({"username":d.username.text(),"password":d.password.text(),"role":d.role.currentText()}), lambda _: self.refresh())
            else: self._error(lambda:self.service.create_user(d.username.text(),d.password.text(),d.role.currentText(),self.actor))
    def edit(self,u):
        d=UserDialog(self,u)
        if d.exec():
            if self.api_mode: self._request(lambda:self.service.update_user(u["id"],{"username":d.username.text(),"role":d.role.currentText(),"is_active":u["is_active"]}), lambda _: self.refresh())
            else: self._error(lambda:self.service.update_user(u["id"],d.username.text(),d.role.currentText(),u["is_active"],self.actor))
    def reset(self,u):
        d=UserDialog(self,u,True)
        if d.exec():
            if self.api_mode: self._request(lambda:self.service.user_action(u["id"],"reset-password",{"password":d.password.text()}), lambda _: self.refresh())
            else: self._error(lambda:self.service.reset_password(u["id"],d.password.text(),self.actor))
    def toggle(self,u):
        if self.api_mode: self._request(lambda:self.service.user_action(u["id"],"enable" if not u["is_active"] else "disable"), lambda _: self.refresh())
        else: self._error(lambda:self.service.set_active(u["id"],not u["is_active"],self.actor))
