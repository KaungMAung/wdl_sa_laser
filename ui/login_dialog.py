from PySide6.QtCore import QThread
from PySide6.QtWidgets import QDialog,QFormLayout,QInputDialog,QLabel,QLineEdit,QMessageBox,QPushButton,QVBoxLayout
from services.api_client import ApiError
from ui.api_workers import ApiWorker

class LoginDialog(QDialog):
    def __init__(self,auth):
        super().__init__(); self.auth=auth; self.token=None; self.user=None; self.setWindowTitle("LaserMaker Login"); self.setMinimumWidth(420)
        self._thread = None; self._worker = None
        root=QVBoxLayout(self); title=QLabel("LASER ENGRAVER/POLISHER"); title.setObjectName("sectionTitle"); root.addWidget(title); form=QFormLayout(); self.username=QLineEdit(); self.password=QLineEdit(); self.password.setEchoMode(QLineEdit.EchoMode.Password); form.addRow("Username",self.username); form.addRow("Password",self.password); root.addLayout(form); self.login_button=QPushButton("LOGIN"); self.login_button.setObjectName("primaryButton"); self.login_button.clicked.connect(self.login); root.addWidget(self.login_button); self.password.returnPressed.connect(self.login); self.username.setFocus()
    def login(self):
        if hasattr(self.auth, "token"):
            self.login_button.setEnabled(False); self.login_button.setText("CONNECTING...")
            self._thread = QThread(self); self._worker = ApiWorker(self._api_login_request); self._worker.moveToThread(self._thread); self._thread.started.connect(self._worker.run); self._worker.succeeded.connect(self._api_login_ok); self._worker.failed.connect(self._api_login_failed); self._worker.finished.connect(self._thread.quit); self._worker.finished.connect(self._worker.deleteLater); self._thread.finished.connect(self._thread.deleteLater); self._thread.start(); return
        try:
            result = self.auth.login(self.username.text(), self.password.text())
            if isinstance(result, tuple):
                self.token, self.user, _ = result
            else:
                self.token = getattr(self.auth, "token", None)
                self.user = result
        except Exception as e:QMessageBox.warning(self,"Login",str(e));self.password.clear();self.password.setFocus();return
        if self.user.get("must_change_password") and hasattr(self.auth, "change_password"):
            QMessageBox.information(self,"Password Change Required","The initial password must be changed before continuing.")
            while True:
                value, ok = QInputDialog.getText(self,"Change Password","New password (minimum 4 characters):",QLineEdit.EchoMode.Password)
                if not ok:return
                try:self.auth.change_password(self.user["id"],value);break
                except Exception as error:QMessageBox.warning(self,"Password",str(error))
        self.accept()

    def _api_login_ok(self, user):
        self.user = user; self.token = getattr(self.auth, "token", None); self.login_button.setEnabled(True); self.login_button.setText("LOGIN"); self.accept()

    def _api_login_failed(self, message):
        self.login_button.setEnabled(True); self.login_button.setText("LOGIN"); QMessageBox.warning(self, "Login", message); self.password.clear(); self.password.setFocus()

    def _api_login_request(self):
        self.auth.login(self.username.text(), self.password.text())
        return self.auth.me()
