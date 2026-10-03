from __future__ import annotations
import hashlib, hmac, logging, os, secrets, sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOGGER = logging.getLogger(__name__)
ROLES = ("Admin", "Engineer", "Operator")

class AuthError(ValueError): pass
class AuthorizationError(PermissionError): pass

class AuthService:
    def __init__(self, database_path: Path | None = None, session_hours: int = 8):
        root=Path(__file__).resolve().parents[1]; self.path=database_path or root/"data"/"lasermaker.db"; self.session_hours=session_hours; self.sessions={}; self.initialize()
    @contextmanager
    def _db(self):
        db=sqlite3.connect(self.path,timeout=5); db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()
    def initialize(self):
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('Admin','Engineer','Operator')), is_active INTEGER NOT NULL DEFAULT 1, must_change_password INTEGER NOT NULL DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
            count=db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count==0:
            username=os.getenv("LASERMAKER_ADMIN_USERNAME","admin").strip() or "admin"; password=os.getenv("LASERMAKER_ADMIN_PASSWORD","ChangeMe123!"); default="LASERMAKER_ADMIN_PASSWORD" not in os.environ
            self.create_user(username,password,"Admin",actor={"username":"SYSTEM","role":"Admin"},must_change=default)
            LOGGER.warning("Initial Admin created: username=%s%s",username,"; change default password immediately" if default else "")
    @staticmethod
    def hash_password(password):
        if len(password)<4: raise AuthError("Password must be at least 4 characters")
        salt=secrets.token_bytes(16); rounds=310000; digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,rounds)
        return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"
    @staticmethod
    def verify_password(password, stored):
        try: _,rounds,salt,digest=stored.split("$"); actual=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),int(rounds)); return hmac.compare_digest(actual,bytes.fromhex(digest))
        except Exception: return False
    @staticmethod
    def public(row):
        return {k:row[k] for k in ("id","username","role","is_active","must_change_password","created_at","updated_at")}
    def audit(self,actor,action,target,result="success"):
        LOGGER.info("AUDIT actor=%s action=%s target=%s result=%s",actor,action,target,result)
    def login(self,username,password):
        with self._db() as db: row=db.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE",(username.strip(),)).fetchone()
        if not row or not row["is_active"] or not self.verify_password(password,row["password_hash"]): self.audit(username,"login","self","failure"); raise AuthError("Invalid username or password")
        token=secrets.token_urlsafe(32); expires=datetime.now(timezone.utc)+timedelta(hours=self.session_hours); user=self.public(row); self.sessions[token]=(user,expires); self.audit(user["username"],"login","self"); return token,user,expires
    def logout(self,token):
        session=self.sessions.pop(token,None)
        if session:self.audit(session[0]["username"],"logout","self")
    def current_user(self,token):
        session=self.sessions.get(token)
        if not session:return None
        user,expires=session
        if expires<=datetime.now(timezone.utc): self.sessions.pop(token,None); return None
        with self._db() as db: row=db.execute("SELECT * FROM users WHERE id=? AND is_active=1",(user["id"],)).fetchone()
        return self.public(row) if row else None
    def require(self,token,*roles):
        user=self.current_user(token)
        if not user: raise AuthorizationError("Authentication required")
        if roles and user["role"] not in roles: raise AuthorizationError("Unauthorized")
        return user
    def list_users(self,actor): self._admin(actor); return self._list()
    def _list(self):
        with self._db() as db: return [self.public(r) for r in db.execute("SELECT * FROM users ORDER BY username")]
    @staticmethod
    def _admin(actor):
        if not actor or actor.get("role")!="Admin": raise AuthorizationError("Admin role required")
    def create_user(self,username,password,role,actor,must_change=False):
        self._admin(actor); username=username.strip()
        if not username:raise AuthError("Username is required")
        if role not in ROLES:raise AuthError("Invalid role")
        try:
            with self._db() as db: row_id=db.execute("INSERT INTO users(username,password_hash,role,must_change_password) VALUES(?,?,?,?)",(username,self.hash_password(password),role,int(must_change))).lastrowid; row=db.execute("SELECT * FROM users WHERE id=?",(row_id,)).fetchone()
        except sqlite3.IntegrityError as e: raise AuthError("Username already exists") from e
        self.audit(actor["username"],"user_created",username); return self.public(row)
    def _get(self,user_id):
        with self._db() as db:return db.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone()
    def _protect_last_admin(self,row,new_role=None,new_active=None):
        if row["role"]!="Admin" or not row["is_active"]:return
        losing=(new_role is not None and new_role!="Admin") or new_active==0
        if losing:
            with self._db() as db: count=db.execute("SELECT COUNT(*) FROM users WHERE role='Admin' AND is_active=1").fetchone()[0]
            if count<=1:raise AuthError("At least one active Admin account is required.")
    def update_user(self,user_id,username,role,is_active,actor):
        self._admin(actor); row=self._get(user_id)
        if not row:raise AuthError("User not found")
        if role not in ROLES:raise AuthError("Invalid role")
        self._protect_last_admin(row,role,int(bool(is_active)))
        with self._db() as db: db.execute("UPDATE users SET username=?,role=?,is_active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(username.strip(),role,int(bool(is_active)),user_id))
        self.audit(actor["username"],"user_updated",username)
        if role != row["role"]: self.audit(actor["username"],"user_role_changed",f"{row['username']}:{row['role']}->{role}")
        if bool(is_active) != bool(row["is_active"]): self.audit(actor["username"],"user_enabled" if is_active else "user_disabled",username)
        return self.public(self._get(user_id))
    def set_active(self,user_id,active,actor):
        row=self._get(user_id)
        if not row:raise AuthError("User not found")
        return self.update_user(user_id,row["username"],row["role"],active,actor)
    def reset_password(self,user_id,password,actor):
        self._admin(actor); row=self._get(user_id)
        if not row:raise AuthError("User not found")
        with self._db() as db:db.execute("UPDATE users SET password_hash=?,must_change_password=1,updated_at=CURRENT_TIMESTAMP WHERE id=?",(self.hash_password(password),user_id))
        self.audit(actor["username"],"password_reset",row["username"])
    def change_password(self, user_id, password):
        encoded = self.hash_password(password)
        with self._db() as db:
            db.execute("UPDATE users SET password_hash=?, must_change_password=0, updated_at=CURRENT_TIMESTAMP WHERE id=?", (encoded, user_id))
