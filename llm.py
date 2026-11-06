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
import time
import urllib.error
import urllib.parse
import urllib.request

import tlog
from net import NoRedirect, classify

log = tlog.get("llm")

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


def _chat_stream(url, body, key, idle, deadline, ctx=None):
    """POST mit Streaming. `idle` = längste Pause ohne ein Byte (die erste Antwort braucht bei grossen Modellen oft lange,
    weil das Modell erst geladen wird), `deadline` = Obergrenze für alles. Gibt (Text, Sekunden bis zum ersten Zeichen) zurück."""
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=json.dumps(dict(body, stream=True)).encode("utf-8"), headers=headers)
    opener = urllib.request.build_opener(NoRedirect, *([urllib.request.HTTPSHandler(context=ctx)] if ctx else []))
    t0 = time.time()
    first, parts = None, []
    try:
        with opener.open(req, timeout=idle) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line or line == "[DONE]":
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                piece = ""
                if isinstance(d.get("message"), dict):                       # Ollama
                    piece = d["message"].get("content") or ""
                elif d.get("choices"):                                       # OpenAI: Strom (delta) oder fertige Antwort (message)
                    c0 = d["choices"][0]
                    piece = ((c0.get("delta") or c0.get("message") or {}).get("content")) or ""
                if piece and first is None:
                    first = time.time() - t0
                parts.append(piece)
                if time.time() - t0 > deadline:
                    raise LlmError("Das Modell war nach %d s noch nicht fertig (Obergrenze). Kleineres oder schnelleres Modell nehmen." % deadline)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read(500).decode("utf-8", "replace")
        except Exception:
            pass
        hint = " (Zugangsschlüssel falsch?)" if e.code in (401, 403) else " (Modellname falsch?)" if e.code == 404 else ""
        raise LlmError("HTTP %s%s %s" % (e.code, hint, detail.strip()[:200]))
    except (socket.timeout, TimeoutError):
        raise LlmError("Seit %d s kam keine Antwort, nach %.0f s abgebrochen. Ein grosses Modell wird beim ersten Aufruf erst geladen; "
                       "dann hilft ein höherer Timeout in den Einstellungen oder ein erster Aufruf direkt am Server." % (idle, time.time() - t0))
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            raise LlmError("Keine Verbindung innerhalb von %d s zustande gekommen." % idle)
        raise LlmError(classify(e)[1])
    except OSError as e:
        raise LlmError(classify(e)[1])
    text = "".join(parts).strip()
    if not text:
        raise LlmError("Das Modell hat nichts geantwortet (leere Antwort). Läuft es mit einem Chat-Format? Modellname prüfen.")
    return text, first


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
        d = _request(cfg["url"].rstrip("/") + "/api/tags", key=key, timeout=15, ctx=ctx)
        return [m.get("name", "") for m in d.get("models", [])]

    def chat(self, cfg, key, system, user, ctx=None):
        return _chat_stream(cfg["url"].rstrip("/") + "/api/chat", {
            "model": cfg["model"], "format": "json",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": 0.2, "num_predict": int(cfg.get("max_tokens", 1500))}},
            key, int(cfg.get("timeout", 120)), int(cfg.get("deadline", 600)), ctx)


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
        return _chat_stream(base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions"), {
            "model": cfg.get("model") or "local", "temperature": 0.2, "max_tokens": int(cfg.get("max_tokens", 1500)),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            key, int(cfg.get("timeout", 120)), int(cfg.get("deadline", 600)), ctx)


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
    prompt = build_prompt(ctx, hint)
    host = urllib.parse.urlparse(url).netloc
    log.info("Anfrage an %s (%s, Modell %s): %d Zeichen Prompt, Idle-Timeout %s s", host, c.get("provider"), c.get("model") or "-", len(prompt), c.get("timeout", 120))
    log.debug("Prompt:\n%s", prompt)
    t0 = time.time()
    try:
        text, first = provider_for(c).chat(c, key, SYSTEM, prompt, ssl_ctx)
    except LlmError as e:
        log.warning("Anfrage an %s fehlgeschlagen nach %.1f s: %s", host, time.time() - t0, e)
        raise
    log.info("Antwort von %s nach %.1f s (erstes Zeichen nach %.1f s), %d Zeichen", host, time.time() - t0, first or 0, len(text))
    log.debug("Antwort:\n%s", text)
    try:
        return parse_draft(text, ctx.get("issue_types"))
    except LlmError as e:
        log.warning("Antwort nicht auswertbar: %s", e)
        raise


# ------------------------------------------------------------ Ideen (0.20): bewerten und als Ticket ausformulieren
CATEGORIES = ("Bugfix", "Feature", "Betrieb", "Doku", "Forschung")
EFFORTS = ("S", "M", "L")
RECOMMEND = ("jetzt", "später", "verwerfen")

SYSTEM_ASSESS = (
    "Du hilfst einem Entwickler, seine Ideenbox zu sortieren. Er neigt dazu, zu viel gleichzeitig anzufangen: Sei streng. "
    "Bewerte genau EINE Idee. Erfinde keine Fakten. Antworte ausschliesslich mit einem JSON-Objekt mit den Feldern: "
    '"category" (Bugfix, Feature, Betrieb, Doku oder Forschung), "benefit" (1, 2 oder 3; 3 = grosser Nutzen), '
    '"effort" (S, M oder L), "effort_why" (ein Satz), "duplicates" (Liste der Nummern ähnlicher Ideen aus der Liste, sonst leer), '
    '"recommendation" (jetzt, später oder verwerfen), "why" (höchstens zwei Sätze).'
)


def assess_prompt(idea, others, tasks=()):
    lines = ["Zu bewertende Idee (#%d, %d Tage alt):" % (idea["id"], idea.get("age_days", 0)), idea["text"][:2000], ""]
    if others:
        lines.append("Andere offene Ideen (für Dubletten):")
        lines += ["- #%d %s" % (o["id"], o["text"].replace("\n", " ")[:200]) for o in others[:30]]
    if tasks:
        lines.append("Laufende Vorhaben (Titel):")
        lines += ["- %s" % t[:120] for t in list(tasks)[:30]]
    return "\n".join(lines)


def parse_assessment(text, valid_ids=()):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise LlmError("Das Modell hat kein JSON geliefert. Antwort: %s" % (text or "")[:200])
    try:
        d = json.loads(m.group(0))
    except ValueError:
        raise LlmError("Das Modell hat ungültiges JSON geliefert.")
    pick = lambda v, allowed: next((a for a in allowed if str(v or "").strip().lower() == a.lower()), "")
    try:
        benefit = int(d.get("benefit"))
    except (TypeError, ValueError):
        benefit = 0
    dups = []
    for x in d.get("duplicates") or []:
        try:
            n = int(str(x).lstrip("#"))
        except ValueError:
            continue
        if n in set(valid_ids):
            dups.append(n)
    out = {"category": pick(d.get("category"), CATEGORIES), "benefit": benefit if benefit in (1, 2, 3) else 0,
           "effort": pick(d.get("effort"), EFFORTS), "effort_why": str(d.get("effort_why") or "")[:300],
           "duplicates": sorted(set(dups)), "recommendation": pick(d.get("recommendation"), RECOMMEND), "why": str(d.get("why") or "")[:500]}
    if not out["recommendation"]:
        raise LlmError("Das Modell hat keine Empfehlung (jetzt, später, verwerfen) geliefert.")
    return out


def _ask(cfg, key, system, prompt, ssl_ctx=None, what="Anfrage"):
    url = check_url(cfg)
    c = dict(cfg, url=url)
    host = urllib.parse.urlparse(url).netloc
    log.info("%s an %s (%s, Modell %s): %d Zeichen", what, host, c.get("provider"), c.get("model") or "-", len(prompt))
    log.debug("Prompt:\n%s", prompt)
    t0 = time.time()
    text, first = provider_for(c).chat(c, key, system, prompt, ssl_ctx)
    log.info("Antwort von %s nach %.1f s, %d Zeichen", host, time.time() - t0, len(text))
    return text


def assess_idea(cfg, key, idea, others, tasks=(), ssl_ctx=None):
    text = _ask(cfg, key, SYSTEM_ASSESS, assess_prompt(idea, others, tasks), ssl_ctx, "Ideen-Bewertung")
    return parse_assessment(text, [o["id"] for o in others])


SYSTEM_IDEA = (
    "Du hilfst einem Entwickler, aus einer Idee ein Jira-Ticket zu machen. Schreibe auf Deutsch, sachlich und knapp. "
    "Erfinde nichts: Was nicht in der Idee steht, gehört als Frage unter «Offene Fragen». "
    "Antworte ausschliesslich mit einem JSON-Objekt mit den Feldern: "
    '"summary" (Titel, höchstens 100 Zeichen), '
    '"description" (Jira-Wiki-Markup mit genau diesen Abschnitten: h3. Story (Als … möchte ich …, damit …), '
    'h3. Akzeptanzkriterien (Liste mit "* "), h3. Risiken, h3. Tests, h3. Abhängigkeiten, h3. Offene Fragen), '
    '"issue_type" (einer der erlaubten Typen).'
)


def idea_prompt(ctx, hint=""):
    lines = ["Idee (#%s):" % ctx.get("idea_id"), (ctx.get("idea_text") or "")[:2000]]
    a = ctx.get("assessment") or {}
    if a:
        lines.append("Bewertung: Kategorie %s, Nutzen %s, Aufwand %s. %s" % (a.get("category") or "?", a.get("benefit") or "?", a.get("effort") or "?", a.get("why") or ""))
    lines.append("Erlaubte Vorgangstypen: %s" % ", ".join(ctx.get("issue_types") or ["Story"]))
    if hint.strip():
        lines.append("Hinweis des Entwicklers: %s" % hint.strip()[:500])
    return "\n".join(lines)


def draft_from_idea(cfg, key, ctx, hint="", ssl_ctx=None):
    text = _ask(cfg, key, SYSTEM_IDEA, idea_prompt(ctx, hint), ssl_ctx, "Ticket aus Idee")
    return parse_draft(text, ctx.get("issue_types"))


def template_from_idea(ctx):
    """Ohne Modell: die Idee in die Abschnitte einsortiert, Lücken als Platzhalter."""
    text = (ctx.get("idea_text") or "").strip()
    first = text.splitlines()[0] if text else "Idee"
    rest = "\n".join(text.splitlines()[1:]).strip()
    a = ctx.get("assessment") or {}
    parts = ["h3. Story", "Als (Rolle) möchte ich %s, damit (Nutzen)." % first.rstrip(".")]
    if rest:
        parts += ["", rest[:2000]]
    if a.get("why"):
        parts += ["", "Bewertung: %s" % a["why"]]
    parts += ["", "h3. Akzeptanzkriterien", "* (noch auszufüllen)", "", "h3. Risiken", "* (noch auszufüllen)", "", "h3. Tests",
              "* (noch auszufüllen)", "", "h3. Abhängigkeiten", "* keine bekannt", "", "h3. Offene Fragen", "* (noch auszufüllen)", "",
              "Aus Idee #%s." % ctx.get("idea_id")]
    return {"summary": first[:255], "description": "\n".join(parts), "issue_type": ""}


def acceptance_items(description):
    """Die Punkte unter «h3. Akzeptanzkriterien» (für Teilschritte). Platzhalter zählen nicht."""
    out, on = [], False
    for ln in (description or "").splitlines():
        s = ln.strip()
        if s.lower().startswith("h3."):
            on = "akzeptanz" in s.lower()
            continue
        if on and s.startswith(("* ", "- ", "# ")):
            t = s[2:].strip()
            if t and not t.startswith("(noch"):
                out.append(t[:200])
    return out[:20]


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
    log.info("Test: Anbieter %s, Adresse %s, Modell %s", cfg.get("provider"), cfg.get("url"), cfg.get("model") or "-")
    try:
        url = check_url(cfg)
        steps.append(("ok", "Adresse", "%s (%s)" % (url, "eigenes Netz" if is_local(url) else "extern erlaubt"), ""))
    except LlmError as e:
        return [("fail", "Adresse", str(e), "Lokal: Ollama hört auf http://127.0.0.1:11434, llama-server meist auf http://127.0.0.1:8080.")], models
    try:
        p = provider_for(cfg)
        c = dict(cfg, url=url)
        t1 = time.time()
        models = p.models(c, key, ssl_ctx)
        steps.append(("ok", "Server antwortet", "%s, %d Modell(e) gefunden (%.1f s)" % (p.label, len(models), time.time() - t1), ""))
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
        t2 = time.time()
        d = draft_ticket(dict(cfg, max_tokens=min(int(cfg.get("max_tokens", 1500)), 400)), key, sample, ssl_ctx=ssl_ctx)
        steps.append(("ok", "Testentwurf", "Titel: «%s» (%.1f s)" % (d["summary"], time.time() - t2), ""))
    except LlmError as e:
        steps.append(("warn", "Testentwurf", str(e), "Verbindung steht, aber der Testentwurf hat nicht geklappt. Meist: das Modell wird erst geladen (Timeout erhöhen und noch einmal testen) oder es antwortet nicht als JSON (anderes Modell)."))
    for st, title, detail, _ in steps:
        (log.info if st == "ok" else log.warning)("Test %s: %s – %s", title, st, detail)
    return steps, models
