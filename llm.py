"""Lokales Sprachmodell für Ticket-Entwürfe (und später weitere Aufgaben).

Eingebaut sind zwei Dialekte, die fast alle lokalen Server sprechen:
  ollama  Ollama (/api/chat, /api/tags)
  openai  OpenAI-kompatibel: llama.cpp (llama-server), LM Studio, vLLM, LocalAI, Jan ... (/v1/chat/completions, /v1/models)

Datenschutz (DLP): Standardmäßig akzeptiert tinyops nur Adressen im eigenen Netz (localhost, private Adressen, Namen ohne Punkt,
.local/.lan/.internal). Eine Adresse im Internet braucht `llm.allow_remote: true`, und dann geht jede Anfrage dorthin.
Gesendet werden nur Titel, Branch-Name, MR-Beschreibung und Commit-Titel, nie Diffs oder Dateiinhalte.

Weitere Anbieter: eine Klasse mit models() und chat() schreiben und mit register() eintragen.
"""
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from net import NoRedirect, classify

LOCAL_SUFFIXES = (".local", ".lan", ".internal", ".intranet", ".home.arpa")


class LlmError(Exception):
    pass


def is_local(url):
    """Liegt der Server im eigenen Netz? Löst Namen auf; ist ein Name nicht auflösbar, gilt er als nicht lokal."""
    host = urllib.parse.urlparse(url).hostname or ""
    if not host:
        return False
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES) or "." not in host and not re.fullmatch(r"[0-9a-fA-F:]+", host):
        return True
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            ips = [ipaddress.ip_address(i[4][0]) for i in socket.getaddrinfo(host, None)]
        except OSError:
            return False
    return bool(ips) and all(ip.is_loopback or ip.is_private or ip.is_link_local for ip in ips)


def check_url(cfg):
    url = (cfg.get("url") or "").strip().rstrip("/")
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise LlmError("Adresse fehlt oder ist ungültig (erwartet zum Beispiel http://127.0.0.1:11434).")
    if not cfg.get("allow_remote") and not is_local(url):
        raise LlmError("«%s» liegt nicht im eigenen Netz. Aus Datenschutzgründen (Kundendaten, Quellcode) sendet tinyops dorthin nichts, "
                       "solange «Externe Adresse erlauben» aus ist." % u.hostname)
    return url


def _request(url, body=None, key="", timeout=120, ctx=None):
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8") if body is not None else None, headers=headers)
    opener = urllib.request.build_opener(NoRedirect, *([urllib.request.HTTPSHandler(context=ctx)] if ctx else []))
    try:
        with opener.open(req, timeout=timeout) as r:
            return json.loads(r.read(4_000_000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read(500).decode("utf-8", "replace")
        except Exception:
            pass
        hint = " (Zugangsschlüssel falsch?)" if e.code in (401, 403) else " (Modellname falsch?)" if e.code == 404 else ""
        raise LlmError("HTTP %s%s %s" % (e.code, hint, detail.strip()[:200]))
    except (urllib.error.URLError, OSError) as e:
        raise LlmError(classify(e)[1])
    except ValueError:
        raise LlmError("Antwort ist kein JSON (falsche Adresse oder falscher Dialekt?).")


class Ollama:
    name = "ollama"
    label = "Ollama"
    default_url = "http://127.0.0.1:11434"

    def models(self, cfg, key, ctx=None):
        d = _request(cfg["url"].rstrip("/") + "/api/tags", key=key, timeout=10, ctx=ctx)
        return [m.get("name", "") for m in d.get("models", [])]

    def chat(self, cfg, key, system, user, ctx=None):
        d = _request(cfg["url"].rstrip("/") + "/api/chat", {
            "model": cfg["model"], "stream": False, "format": "json",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": 0.2}}, key, int(cfg.get("timeout", 120)), ctx)
        return ((d.get("message") or {}).get("content") or "").strip()


class OpenAICompat:
    name = "openai"
    label = "OpenAI-kompatibel (llama.cpp, LM Studio, vLLM ...)"
    default_url = "http://127.0.0.1:8080"

    def models(self, cfg, key, ctx=None):
        base = cfg["url"].rstrip("/")
        d = _request(base + ("/models" if base.endswith("/v1") else "/v1/models"), key=key, timeout=10, ctx=ctx)
        return [m.get("id", "") for m in d.get("data", [])]

    def chat(self, cfg, key, system, user, ctx=None):
        base = cfg["url"].rstrip("/")
        d = _request(base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions"), {
            "model": cfg.get("model") or "local", "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            key, int(cfg.get("timeout", 120)), ctx)
        try:
            return (d["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            raise LlmError("Antwort hat nicht das erwartete Format (choices[0].message.content).")


PROVIDERS = {}


def register(provider):
    PROVIDERS[provider.name] = provider


register(Ollama())
register(OpenAICompat())


def provider_for(cfg):
    p = PROVIDERS.get(cfg.get("provider") or "ollama")
    if not p:
        raise LlmError("Unbekannter Anbieter «%s». Erlaubt: %s." % (cfg.get("provider"), ", ".join(PROVIDERS)))
    return p


def ready(cfg):
    return bool(cfg.get("enabled") and cfg.get("url") and (cfg.get("model") or cfg.get("provider") == "openai"))


# ------------------------------------------------------------ Ticket-Entwurf
SYSTEM = (
    "Du hilfst einem Entwickler, ein Jira-Ticket zu schreiben. Schreibe auf Deutsch, sachlich und knapp. "
    "Erfinde nichts: Nutze nur die gelieferten Angaben. Wenn etwas unklar ist, schreibe es als offene Frage. "
    "Antworte ausschließlich mit einem JSON-Objekt mit den Feldern: "
    '"summary" (Titel, höchstens 100 Zeichen, ohne Ticket-Nummer), '
    '"description" (Jira-Wiki-Markup mit den Abschnitten h3. Ausgangslage, h3. Ziel, h3. Akzeptanzkriterien als Liste mit "* ", h3. Offene Fragen), '
    '"issue_type" (einer der erlaubten Typen).'
)


def build_prompt(ctx, hint=""):
    lines = ["Quelle: %s" % ("Merge Request" if ctx.get("iid") else "Branch ohne Merge Request"),
             "Projekt: %s" % ctx.get("project", ""), "Titel: %s" % ctx.get("title", ""), "Branch: %s" % ctx.get("branch", "")]
    if ctx.get("mr_description"):
        lines.append("MR-Beschreibung:\n%s" % ctx["mr_description"][:2000])
    if ctx.get("commits"):
        lines.append("Commits (neueste zuerst):\n" + "\n".join("- " + c for c in ctx["commits"][:20]))
    lines.append("Erlaubte Vorgangstypen: %s" % ", ".join(ctx.get("issue_types") or ["Story"]))
    if hint.strip():
        lines.append("Hinweis des Entwicklers: %s" % hint.strip()[:500])
    return "\n".join(lines)


def parse_draft(text, allowed_types):
    """Holt das JSON aus der Antwort (auch wenn das Modell Text oder Codezäune drumherum schreibt)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise LlmError("Das Modell hat kein JSON geliefert. Antwort: %s" % (text or "")[:200])
    try:
        d = json.loads(m.group(0))
    except ValueError:
        raise LlmError("Das Modell hat ungültiges JSON geliefert. Ein größeres Modell oder ein Modell mit JSON-Modus hilft.")
    desc = d.get("description") or ""
    if isinstance(desc, (list, dict)):
        desc = json.dumps(desc, ensure_ascii=False)
    out = {"summary": str(d.get("summary") or "").strip()[:255], "description": str(desc).strip()[:30000],
           "issue_type": str(d.get("issue_type") or "").strip()}
    if not out["summary"]:
        raise LlmError("Das Modell hat keinen Titel geliefert.")
    low = {t.lower(): t for t in allowed_types or []}
    out["issue_type"] = low.get(out["issue_type"].lower(), "")
    return out


def draft_ticket(cfg, key, ctx, hint="", ssl_ctx=None):
    url = check_url(cfg)
    c = dict(cfg, url=url)
    text = provider_for(c).chat(c, key, SYSTEM, build_prompt(ctx, hint), ssl_ctx)
    return parse_draft(text, ctx.get("issue_types"))


def template_draft(ctx):
    """Entwurf ohne Modell: nur Umformen dessen, was schon da ist. Läuft immer."""
    title = re.sub(r"^(wip|draft)[:\s]+", "", (ctx.get("title") or ""), flags=re.I).strip()
    parts = ["h3. Ausgangslage",
             ("Quelle: %s %s" % ("Merge Request", ctx.get("url", "")) if ctx.get("iid") else "Quelle: Branch %s (%s)" % (ctx.get("branch", ""), ctx.get("url", ""))).strip()]
    if ctx.get("mr_description"):
        parts += ["", ctx["mr_description"][:2000]]
    if ctx.get("commits"):
        parts += ["", "Bisherige Commits:"] + ["* " + c for c in ctx["commits"][:15]]
    parts += ["", "h3. Ziel", "(noch auszufüllen)", "", "h3. Akzeptanzkriterien", "* (noch auszufüllen)"]
    return {"summary": title[:255], "description": "\n".join(parts), "issue_type": ""}


def test(cfg, key, ssl_ctx=None):
    """Prüft Schritt für Schritt. Gibt (Schritte, Modelle) zurück; jeder Schritt (status, Titel, Detail, Hinweis)."""
    steps, models = [], []
    try:
        url = check_url(cfg)
        steps.append(("ok", "Adresse", "%s (%s)" % (url, "eigenes Netz" if is_local(url) else "extern erlaubt"), ""))
    except LlmError as e:
        return [("fail", "Adresse", str(e), "Lokal: Ollama hört auf http://127.0.0.1:11434, llama-server meist auf http://127.0.0.1:8080.")], models
    try:
        p = provider_for(cfg)
        c = dict(cfg, url=url)
        models = p.models(c, key, ssl_ctx)
        steps.append(("ok", "Server antwortet", "%s, %d Modell(e) gefunden" % (p.label, len(models)), ""))
    except LlmError as e:
        hint = "Läuft der Server? Ollama: «ollama serve». llama.cpp: «llama-server -m modell.gguf». Falscher Dialekt? Dann den anderen Anbieter wählen."
        steps.append(("fail", "Server antwortet", str(e), hint))
        return steps, models
    model = cfg.get("model") or ""
    if p.name == "ollama" and not model:
        steps.append(("fail", "Modell", "Kein Modell gewählt.", "Eines aus der Liste eintragen (Klick auf einen Namen unten)."))
        return steps, models
    if model and models and model not in models and p.name == "ollama":
        steps.append(("fail", "Modell", "«%s» ist nicht installiert." % model, "Mit «ollama pull %s» laden oder eines der gefundenen Modelle nehmen." % model))
        return steps, models
    steps.append(("ok", "Modell", model or "(vom Server gewählt)", ""))
    try:
        sample = {"title": "Retry bei HTTP 429 im Adapter", "branch": "feature/retry-429", "project": "demo", "commits": ["Retry mit Backoff"],
                  "issue_types": ["Story", "Bug"]}
        d = draft_ticket(cfg, key, sample, ssl_ctx=ssl_ctx)
        steps.append(("ok", "Testentwurf", "Titel: %s" % d["summary"], ""))
    except LlmError as e:
        steps.append(("warn", "Testentwurf", str(e), "Verbindung steht, aber das Modell antwortet nicht brauchbar. Anderes Modell probieren."))
    return steps, models
