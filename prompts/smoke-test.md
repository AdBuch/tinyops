Prüfe die Testumgebung für Merge Request !{mr_iid} ({project}, Branch {branch}).

Namespace: {namespace} (Cluster-Kontext: {context}). Arbeite ausschließlich in diesem Namespace, nur lesend
(kubectl get/describe/logs). Ändere, lösche oder skaliere nichts.

1. Laufen alle Pods bereit? Falls nicht: Events und Logs der betroffenen Pods zusammenfassen.
2. Gibt es Fehler oder Warnungen in den Logs der letzten 10 Minuten (gruppiert, ohne Wiederholungen)?
3. Antworten die Health-/Readiness-Endpunkte?
4. Liste 5 konkrete Klickpfade oder Aufrufe, die ich von Hand prüfen sollte, passend zu: "{title}".

Gib am Ende eine Ampel (grün/gelb/rot) mit einem Satz Begründung.
