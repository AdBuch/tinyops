Werkzeuge von tinyops (stehen im PATH dieses Laufs):
- `tinyops-ask "Frage" "Option A" "Option B"` fragt den Menschen und gibt die Antwort aus. Frag, wenn etwas unklar ist oder sich widerspricht, statt zu raten. Endet es mit Exit 3, ist noch keine Antwort da: dann `tinyops-ask --wait <Nr>` aufrufen, nicht neu fragen.
- `tinyops-check <Befehl>` führt Tests oder Builds aus und hält Befehl und Exit-Code als Beleg fest, zum Beispiel `tinyops-check mvn -q test`. Nur so belegte Tests gelten als getestet.
- `tinyops-report` speichert deinen Ergebnisbericht (Markdown, über die Standardeingabe): was geändert, was mit tinyops-check getestet, was offen ist.
