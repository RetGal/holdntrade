# holdntrade

## Voraussetzungen

*holdntrade* setzt *Python* Version 3 oder grösser voraus.
Im Kern verwendet *holdntrade* die [ccxt](https://github.com/ccxt/ccxt) Bibliothek. Diese gilt es mittels [pip](https://pypi.org/project/pip/) zu installieren:

`python -m pip install ccxt`

Sollen die *holdntrade* Instanzen via Watchdog überwacht und bei Bedarf nau gestartet werden, so wird zusätzlich noch [tmux](https://github.com/tmux/tmux/wiki) benötigt:

`apt install tmux`


## Inbetriebnahme

Vor dem Start ist die Konfigurationsdatei mit den gewünschten API Keys und Einstellungen zu ergänzen.

Bei der Initialisierung wird jeweils nach dem Namen der Konfigurationsdatei gefragt. Diesen ohne Endung (*.txt*) eingeben. 
Es können also mehrere config Dateien erstellt und immer dieselbe *holdntrade.py* Datei zum Start verwendet werden.

Alternativ kann die zu verwendete Konfigurationsdatei auch als Parameter übergeben werden:

`./holdntrade.py test1`

Mit Hilfe des Watchdog-Scrpits *hades.sh* lässt sich eine beliebige Anzahl Botinstanzen überwachen.
Sollte eine Instanz nicht mehr laufen, wird sie automatisch neu gestartet.

Dazu sollte der Variable *holdntradeDir* der absolute Pfad zum *holdntrade.py* Script angegeben werden.
Voraussetzung ist, dass die *holdntrade.py* Instanzen innerhalb von *tmux* Sessions ausgeführt werden, welche gleich heissen wie die entsprechende Konfigurationsdatei:

Wenn also eine Konfigurationsdatei beispielsweise *test1.txt* heisst, dann sollte *holdntrade.py test1* innerhalb einer *tmux* Session namens *test1* laufen.

Damit *hades.sh* die *holdntrade*  Instanzen kontinuierlich überwachen kann, muss ein entsprechender *Cronjob* eingerichtet werden:

`*/5 *   *   *   *   /home/bit/trader/hades.sh`

Die beiden Dateien *holdntrade.py* und *hades.sh* müssen vor dem ersten Start mittels `chmod +x` ausführbar gemacht werden.


## Unterbrechen

Wenn die *holdntrade* Instanzen via *hades* überwacht werden, steht man vor dem Problem, dass eine gestoppte Instanz nach spätestens 5 Minuten automatisch neu gestartet wird. Will man eine *holdntrade* Instanz für längere Zeit unterbrechen, muss man vor oder nach dessen Terminierung die entsprechende *.pid* Datei umbenennen:

`mv test1.pid test1.did`


## Troubleshooting

Jede Instanz erstellt und schreibt in eine eigene Logdatei. Diese heisst so wie die entsprechende Konfigurationsdatei, endet aber auf *.log*:

`test1.log`

Fehlt diese Datei, dann konnte *holdntrade.py* nicht gestartet werden.
Die nächste Anlaufstelle wäre die entsprechende *tmux* Session:

`tmux a -t test1`

Sieht man da eine Fehlermeldung im Stil von:

`/usr/bin/python^M: bad interpreter`

Dann ist *holdntrade.py* höchstwahrscheinlich in einem Windows Editor bearbeitet worden. Die folgenden Befehlsabfolge behebt das Problem:

`tr -d '\r' < holdntrade.py > holdntrade && mv holdntrade holdntrade.py && chmod +x holdntrade.py`
