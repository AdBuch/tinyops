"""Spracherkennung (0.43): gesprochenen Text für Prompts und Sprachbefehle, nur mit einem Modell im eigenen Netz.

Der Browser nimmt auf und schickt WAV (16 kHz, mono, 16 Bit). tinyops reicht es an deinen lokalen Server weiter und gibt nur den Text zurück.
Die Aufnahme wird nirgends gespeichert, nicht protokolliert und nicht im Nutzungsbericht gezählt; im Log steht nur Länge und Dauer.

Zwei Arten von Servern:
- «openai»: OpenAI-kompatibel, `POST /v1/audio/transcriptions` (multipart: file, model, language). So sprechen vLLM mit Voxtral Mini,
  speaches/faster-whisper und andere.
- «whispercpp»: der Server aus whisper.cpp, `POST /inference` (multipart: file, language, response_format=json).
Wie beim lokalen Sprachmodell: andere Adressen als im eigenen Netz nur mit «Externe Adresse erlauben»."""
import json
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import apicalls
import llm
import tlog
import voicekit

log = tlog.get("tinyops")

KINDS = {"builtin": ("Eingebaut: tinyops richtet whisper.cpp selbst ein (ohne Grafikkarte)", "/inference", "http://127.0.0.1"),
         "openai": ("OpenAI-kompatibel (vLLM mit Voxtral, speaches, faster-whisper)", "/v1/audio/transcriptions", "http://127.0.0.1:8000"),
         "whispercpp": ("whisper.cpp-Server", "/inference", "http://127.0.0.1:8178")}
DEFAULTS = {"enabled": False, "kind": "builtin", "url": "", "model": "", "language": "de", "allow_remote": False,
            "max_seconds": 120, "timeout": 60, "builtin_model": "small", "program": "", "threads": 0}
LANGS = ("de", "en", "fr", "it", "auto")
MAX_BYTES = 16000 * 2 * 300 + 4096          # 5 Minuten WAV, mehr nimmt tinyops nicht an


class VoiceError(Exception):
    pass


def cfg_of(cfg):
    c = dict(DEFAULTS)
    c.update(cfg.get("voice") or {})
    return c


def ready(vc):
    return bool(vc.get("enabled") and (vc.get("url") or vc.get("kind") == "builtin"))


def check_url(vc):
    """Gleiche Regel wie beim lokalen Sprachmodell: nur eigenes Netz, ausser ausdrücklich erlaubt."""
    try:
        return llm.check_url({"url": vc.get("url"), "allow_remote": vc.get("allow_remote")})
    except llm.LlmError as e:
        raise VoiceError(str(e).replace("http://127.0.0.1:11434", KINDS.get(vc.get("kind"), KINDS["whispercpp"])[2]))


def wav_info(data):
    """Prüft, dass es ein WAV mit PCM ist, und nennt Sekunden. Anderes nimmt tinyops nicht an."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise VoiceError("Die Aufnahme ist kein WAV.")
    pos, fmt, size = 12, None, 0
    while pos + 8 <= len(data):
        cid, n = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", data[pos + 8:pos + 24])
        elif cid == b"data":
            size = min(n, len(data) - pos - 8)
            break
        pos += 8 + n + (n & 1)
    if not fmt or fmt[0] != 1 or not size:
        raise VoiceError("Die Aufnahme ist kein PCM-WAV.")
    _, ch, rate, _, _, bits = fmt
    return size / float(rate * ch * bits // 8)


def silence_wav(seconds=1.0, rate=16000):
    n = int(seconds * rate)
    return b"RIFF" + struct.pack("<I", 36 + n * 2) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) \
        + b"data" + struct.pack("<I", n * 2) + b"\0" * (n * 2)


def _multipart(fields, wav):
    b = "----tinyops" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        if v not in (None, ""):
            out.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode("utf-8"))
    out.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"sprache.wav\"\r\nContent-Type: audio/wav\r\n\r\n" % b).encode("utf-8"))
    out.append(wav)
    out.append(("\r\n--%s--\r\n" % b).encode("utf-8"))
    return b"".join(out), "multipart/form-data; boundary=" + b


def transcribe(vc, wav, language=None, key="", ssl_ctx=None):
    """WAV → Text. Gibt (text, sekunden_audio, sekunden_erkennung) zurück."""
    if not ready(vc):
        raise VoiceError("Spracherkennung ist aus. Einstellungen → Sprache: lokalen Server eintragen.")
    if len(wav) > MAX_BYTES:
        raise VoiceError("Die Aufnahme ist zu lang.")
    secs = wav_info(wav)
    if secs > float(vc.get("max_seconds") or 120) + 1:
        raise VoiceError("Die Aufnahme ist länger als %d s." % int(vc.get("max_seconds") or 120))
    base = check_url(vc)
    kind = vc.get("kind") if vc.get("kind") in KINDS else "whispercpp"
    if kind == "builtin":          # Adresse kommt vom eingebauten Server (area_voice → voicekit)
        kind = "whispercpp"
    path = KINDS[kind][1]
    if kind == "openai" and base.endswith("/v1"):           # Adresse mit /v1 eingetragen, wie beim Sprachmodell üblich
        base = base[:-3]
    lang = language or vc.get("language") or "de"
    fields = {"language": "" if lang == "auto" else lang, "temperature": "0", "response_format": "json"}
    if kind == "openai":
        fields["model"] = vc.get("model") or ""
    body, ctype = _multipart(fields, wav)
    headers = {"Content-Type": ctype, "Accept": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(base + path, data=body, headers=headers, method="POST")
    apicalls.record("Spracherkennung", "POST", path)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}) if llm.is_local(base) else urllib.request.ProxyHandler(),
                                         *( [urllib.request.HTTPSHandler(context=ssl_ctx)] if ssl_ctx else []))
    t0 = time.time()
    try:
        with opener.open(req, timeout=float(vc.get("timeout") or 60)) as r:
            raw = r.read(2_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read(400).decode("utf-8", "replace")
        except OSError:
            pass
        hint = {404: " Stimmt die Art des Servers (%s erwartet %s)?" % (KINDS[kind][0], path), 401: " Schlüssel fehlt oder falsch.",
                400: " Kennt der Server das Modell «%s»?" % (vc.get("model") or "-") if kind == "openai" else ""}.get(e.code, "")
        raise VoiceError("Spracherkennung: HTTP %s.%s %s" % (e.code, hint, " ".join(detail.split())[:160]))
    except (urllib.error.URLError, OSError) as e:
        raise VoiceError("Spracherkennung nicht erreichbar (%s). Läuft der Server auf %s?" % (getattr(e, "reason", e), base))
    took = time.time() - t0
    try:
        d = json.loads(raw)
        text = d.get("text") if isinstance(d, dict) else None
    except ValueError:
        text = raw if raw and not raw.lstrip().startswith(("<", "{")) else None
    if text is None:
        raise VoiceError("Spracherkennung: Antwort ohne Text.")
    text = " ".join(str(text).split())
    if text.strip("[]() .").lower() in ("blank_audio", "music", "musik", "silence", ""):
        text = ""
    log.info("Spracherkennung: %.1f s Audio, %.1f s Erkennung, %d Zeichen", secs, took, len(text))
    return text, secs, took


# ---------------------------------------------------------------- Einstellungen (ausserhalb von settings.py, das ist schon gross genug)
def view(cfg):
    vc = cfg_of(cfg)
    return {k: vc.get(k) for k in DEFAULTS} | {"kinds": [{"id": k, "label": v[0], "path": v[1], "url": v[2]} for k, v in KINDS.items()],
                                              "builtin_models": [{"id": k, "file": v[0], "mib": v[1], "about": v[3]} for k, v in voicekit.MODELS.items()]}


def clean(m, cfg, errors):
    vc = dict(cfg_of(cfg))
    vc["enabled"] = bool(m.get("enabled", False))
    vc["kind"] = m.get("kind") if m.get("kind") in KINDS else "whispercpp"
    vc["url"] = (m.get("url") or "").strip().rstrip("/")[:300]
    vc["builtin_model"] = m.get("builtin_model") if m.get("builtin_model") in voicekit.MODELS else "small"
    vc["program"] = (m.get("program") or "").strip()[:500]
    import settings_schema                   # 0.45: Grenzen aus dem Schema (dort importiert es voice, darum erst hier)
    nt = settings_schema.NUMBERS["voice.threads"]
    try:
        vc["threads"] = max(nt.lo, min(nt.hi, int(m.get("threads") or 0)))
    except (TypeError, ValueError):
        errors["voice.threads"] = "Eine Zahl, 0 heisst automatisch."
    vc["model"] = (m.get("model") or "").strip()[:120]
    vc["language"] = m.get("language") if m.get("language") in LANGS else "de"
    vc["allow_remote"] = bool(m.get("allow_remote", False))
    for k in ("max_seconds", "timeout"):
        n = settings_schema.NUMBERS["voice." + k]
        try:
            vc[k] = max(n.lo, min(n.hi, int(m.get(k) if m.get(k) not in (None, "") else DEFAULTS[k])))
        except (TypeError, ValueError):
            errors["voice." + k] = settings_schema.message("voice." + k)
    if vc["kind"] == "openai" and vc["enabled"] and not vc["model"]:
        errors["voice.model"] = "Der OpenAI-kompatible Server braucht den Modellnamen (z. B. mistralai/Voxtral-Mini-3B-2507)."
    if vc["enabled"] and vc["kind"] != "builtin":
        if not vc["url"]:
            errors["voice.url"] = "Adresse des Servers fehlt."
        try:
            check_url(vc)
        except VoiceError as e:
            errors["voice.url"] = str(e)
    cfg["voice"] = vc


def test(form, key=""):
    """Einstellungen → Sprache → Testen: Adresse prüfen, eine Sekunde Stille erkennen lassen. Ergebnis als Schritte."""
    vc = dict(DEFAULTS)
    vc.update({k: form.get(k) for k in ("kind", "url", "model", "language", "allow_remote") if k in form}, enabled=True)
    steps = []
    try:
        base = check_url(vc)
        steps.append(("ok", "Adresse", base + KINDS.get(vc["kind"], KINDS["whispercpp"])[1], ""))
    except VoiceError as e:
        return [("fail", "Adresse", str(e), "")]
    try:
        text, _, took = transcribe(vc, silence_wav(1.0), key=key)
        steps.append(("ok", "Erkennung", "Antwort nach %.1f s%s" % (took, (", Text: «%s»" % text[:60]) if text else ", kein Text (Stille, richtig so)"), ""))
        if took > 8:
            steps.append(("warn", "Tempo", "Eine Sekunde Stille brauchte %.1f s." % took, "Ein kleineres Modell (z. B. whisper small, Voxtral Mini) oder GPU macht das Diktieren angenehmer."))
    except VoiceError as e:
        steps.append(("fail", "Erkennung", str(e), "whisper.cpp: whisper-server -m models/ggml-small.bin --host 127.0.0.1 --port 8178 -l de"))
    return steps
