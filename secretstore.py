"""Secret-Speicher für tinyops. Nur Standardbibliothek, `keyring` ist optional.

Grundregeln:
- Secrets stehen nie in config.json, nie im Projektordner, nie im Browser, nie im Log.
- Quellen in dieser Reihenfolge: Befehl/Umgebungsvariable aus der Config (falls gesetzt),
  sonst Umgebungsvariable TINYOPS_<NAME>, Schlüsselbund des Betriebssystems, Datei
  ~/.config/tinyops/secrets.json (nur für deinen Benutzer lesbar).
"""
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

SERVICE = "tinyops"
NAMES = ("gitlab_token", "jira_token", "jira_password", "access_token", "llm_key", "sonar_token", "github_token")

# Umgebungsvariablen, die Secrets enthalten können: werden Jobs nicht vererbt.
SENSITIVE_ENV = set()
_used = set()


class SecretError(Exception):
    pass


# ------------------------------------------------------------ Schwärzen
def register(value):
    """Merkt sich einen Wert, damit scrub() ihn aus Logs und Fehlern entfernt."""
    if value and len(value) >= 4:
        _used.add(value)


def scrub(text):
    s = str(text)
    for v in sorted(_used, key=len, reverse=True):
        s = s.replace(v, "***")
    return s


# ------------------------------------------------------------ Orte
def home_dir():
    return Path(os.environ.get("TINYOPS_HOME") or (Path.home() / ".config" / "tinyops"))


def secrets_file():
    return home_dir() / "secrets.json"


def _check_name(name):
    if name not in NAMES:
        raise SecretError("Unbekanntes Secret '%s'. Erlaubt: %s" % (name, ", ".join(NAMES)))


# ------------------------------------------------------------ Datei
def _read_file():
    p = secrets_file()
    if not p.exists():
        return {}
    if os.name != "nt":
        st = p.stat()
        if st.st_mode & 0o077:
            raise SecretError("%s ist für andere Benutzer lesbar. Behebe das mit: chmod 600 %s" % (p, p))
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            raise SecretError("%s gehört einem anderen Benutzer, wird nicht gelesen." % p)
        if p.parent.stat().st_mode & 0o022:
            raise SecretError("Ordner %s ist für andere beschreibbar. Behebe das mit: chmod 700 %s" % (p.parent, p.parent))
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        raise SecretError("%s ist kein gültiges JSON." % p)
    if not isinstance(data, dict):
        raise SecretError("%s hat ein unerwartetes Format." % p)
    return data


def _write_file(data):
    d = home_dir()
    existed = d.exists()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not existed and os.name != "nt":
        os.chmod(str(d), 0o700)
    p = secrets_file()
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(str(tmp), str(p))
    if os.name != "nt":
        os.chmod(str(p), 0o600)


# ------------------------------------------------------------ Schlüsselbund (optional)
def _keyring():
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


# ------------------------------------------------------------ Befehl
def _from_cmd(argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        raise SecretError("Secret-Befehl %s fehlgeschlagen: %s" % (argv[0], type(e).__name__))
    if r.returncode != 0:
        raise SecretError("Secret-Befehl %s endete mit Code %d." % (argv[0], r.returncode))
    val = r.stdout.rstrip("\r\n")
    if not val:
        raise SecretError("Secret-Befehl %s lieferte nichts." % argv[0])
    return val


# ------------------------------------------------------------ Auflösen
def _done(value, label):
    register(value)
    return value, label


def resolve(name, spec=None, extra_env=()):
    """Gibt (wert, quelle) zurück oder (None, None). Wirft SecretError bei kaputter Quelle."""
    _check_name(name)
    if spec:
        if isinstance(spec, dict) and spec.get("cmd"):
            cmd = spec["cmd"]
            if not (isinstance(cmd, list) and cmd and all(isinstance(x, str) for x in cmd)):
                raise SecretError("secrets.%s.cmd muss eine Liste von Texten sein." % name)
            return _done(_from_cmd(cmd), "Befehl %s" % cmd[0])
        if isinstance(spec, dict) and spec.get("env"):
            SENSITIVE_ENV.add(spec["env"])
            val = os.environ.get(spec["env"], "")
            return _done(val, "Umgebungsvariable %s" % spec["env"]) if val else (None, None)
        raise SecretError('secrets.%s: erwartet {"cmd": [...]} oder {"env": "NAME"}.' % name)
    for env in ["TINYOPS_" + name.upper()] + [e for e in extra_env if e]:
        SENSITIVE_ENV.add(env)
        val = os.environ.get(env, "")
        if val:
            return _done(val, "Umgebungsvariable %s" % env)
    kr = _keyring()
    if kr:
        try:
            val = kr.get_password(SERVICE, name)
        except Exception:
            val = None
        if val:
            return _done(val, "Schlüsselbund")
    val = _read_file().get(name)
    if isinstance(val, str) and val:
        return _done(val, "Datei %s" % secrets_file())
    return None, None


def require(name, spec=None, extra_env=()):
    val, src = resolve(name, spec, extra_env)
    if not val:
        raise SecretError("Secret '%s' fehlt. Setze es mit: python3 server.py --set-secret %s" % (name, name))
    return val, src


# ------------------------------------------------------------ Ändern
def set_secret(name, value):
    _check_name(name)
    if not value:
        raise SecretError("Leerer Wert, nichts gespeichert.")
    kr = _keyring()
    if kr:
        try:
            kr.set_password(SERVICE, name, value)
            return "Schlüsselbund des Betriebssystems"
        except Exception:
            pass
    data = _read_file() if secrets_file().exists() else {}
    data[name] = value
    _write_file(data)
    return "Datei %s (nur für deinen Benutzer lesbar, Klartext)" % secrets_file()


def delete_secret(name):
    _check_name(name)
    removed = []
    kr = _keyring()
    if kr:
        try:
            if kr.get_password(SERVICE, name):
                kr.delete_password(SERVICE, name)
                removed.append("Schlüsselbund")
        except Exception:
            pass
    if secrets_file().exists():
        data = _read_file()
        if name in data:
            del data[name]
            _write_file(data)
            removed.append("Datei")
    return removed


def read_secret_interactive(name):
    """Fragt ohne Echo ab. Ohne Terminal (Pipe) wird eine Zeile von stdin gelesen."""
    if sys.stdin.isatty():
        return getpass.getpass("Wert für %s (Eingabe bleibt unsichtbar): " % name)
    return sys.stdin.readline().rstrip("\r\n")


def describe(specs, extra_env):
    """Textzeilen: wo welches Secret herkommt. Nie der Wert selbst."""
    lines = []
    for name in NAMES:
        try:
            val, src = resolve(name, (specs or {}).get(name), extra_env.get(name, ()))
            lines.append("  %-14s %s" % (name, ("← " + src) if val else "nicht gesetzt"))
        except SecretError as e:
            lines.append("  %-14s FEHLER: %s" % (name, e))
    kr = "verfügbar" if _keyring() else "nicht verfügbar (pip install keyring, optional)"
    lines.append("  Schlüsselbund: %s" % kr)
    if os.name == "nt":
        lines.append("  Hinweis: Unter Windows lassen sich Dateirechte hier nicht prüfen. Nimm den Schlüsselbund oder einen Befehl.")
    return lines
