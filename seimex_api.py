"""Cliente Seimex API. Login + cache JWT + get_operations."""
import json, os, time
from pathlib import Path
import requests

BASE = "https://seimex-api.onrender.com"
CACHE_FILE = Path(__file__).parent / "data" / "comex" / ".seimex_token_cache.json"
CACHE_TTL_SEG = 60 * 60 * 12


class SeimexAPIError(Exception): pass


class SeimexAPI:
    def __init__(self, email=None, password=None):
        self.email = email or os.environ.get("SEIMEX_EMAIL")
        self.password = password or os.environ.get("SEIMEX_PASSWORD")
        if not self.email or not self.password:
            raise SeimexAPIError("Faltan SEIMEX_EMAIL / SEIMEX_PASSWORD")
        self._token = None

    def _load_cached_token(self):
        if not CACHE_FILE.exists(): return None
        try:
            d = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if d.get("email") != self.email: return None
            if time.time() - d.get("ts", 0) > CACHE_TTL_SEG: return None
            return d.get("token")
        except Exception: return None

    def _save_cached_token(self, token):
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({"email": self.email, "token": token, "ts": time.time()}), encoding="utf-8")

    def login(self, force=False):
        if not force:
            c = self._load_cached_token()
            if c: self._token = c; return c
        r = requests.post(f"{BASE}/api/v1/auth/login",
            json={"user": {"email": self.email, "password": self.password}},
            headers={"Origin": "https://seimex-frontend.onrender.com"}, timeout=15)
        if r.status_code != 200:
            raise SeimexAPIError(f"Login HTTP {r.status_code}: {r.text[:200]}")
        token = r.json().get("token") or r.headers.get("authorization", "").replace("Bearer ", "")
        if not token: raise SeimexAPIError("Login OK pero no token")
        self._token = token
        self._save_cached_token(token)
        return token

    def _headers(self):
        if not self._token: self.login()
        return {"Authorization": f"Bearer {self._token}", "Origin": "https://seimex-frontend.onrender.com"}

    def _get(self, path, params=None, retry_on_401=True):
        r = requests.get(f"{BASE}{path}", headers=self._headers(), params=params or {}, timeout=30)
        if r.status_code == 401 and retry_on_401:
            self.login(force=True)
            return self._get(path, params, retry_on_401=False)
        if r.status_code != 200:
            raise SeimexAPIError(f"GET {path} HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def get_operations(self, per_page=2000):
        d = self._get("/api/v1/operations", params={"per_page": per_page})
        return d if isinstance(d, list) else d.get("data", d.get("operations", []))

    def find_by_code(self, code):
        c = code.upper()
        ops = self.get_operations()
        matches = [o for o in ops if c in str(o.get("reference_number","")).upper() or c in str(o.get("product","")).upper()]
        if not matches: return None
        matches.sort(key=lambda o: o.get("created_at",""), reverse=True)
        return matches[0]

    @staticmethod
    def resumen_operacion(op):
        if not op: return {}
        return {
            "reference": op.get("reference_number"),
            "product": op.get("product"),
            "supplier": op.get("supplier"),
            "stage": op.get("stage", {}).get("name") if isinstance(op.get("stage"), dict) else None,
            "port_origin": op.get("port_origin"),
            "port_dest": op.get("port_dest"),
            "eta": op.get("eta"),
            "quoted_freight_value": op.get("quoted_freight_value"),
            "quoted_freight_currency": op.get("quoted_freight_currency"),
            "booking": op.get("booking"),
            "departure_confirmed": op.get("departure_confirmed"),
            "reception_confirmed": op.get("reception_confirmed"),
            "has_incident": op.get("has_incident"),
            "updated_at": op.get("updated_at"),
        }
