# holdntrade

Vor dem Start die Konfigurationsdatei mit den gewünschten API Keys und Einstellungen ergänzen.

Bei der Initialisierung wird jeweils nach dem Dateinamen gefragt. Diesen ohne Endung (.txt) eingeben. 
Das heisst, es können nun einfach mehrere config Dateien erstellt und immer dieselbe `holdntrade.py` Datei zum Start verwendet werden.

Alternativ kann die zu verwendete Konfigurationsdatei auch als Parameter übergeben werden:

`./holdntrade.py test1`

Mit Hilfe des Watchdog-Scrpits `hades.sh` lässt sich eine beliebige Anzahl Botinstanzen überwachen.
Sollte eine Instanz nicht mehr laufen, wird sie automatisch neu gestartet.

Dazu sollte der Variable `holdntradeDir` der absolute Pfad zum `holdntrade.py` Script angegeben werden.
Voraussetzung ist, dass die `holdntrade.py` Instanzen innerhalb von *tmux* Sessions ausgeführt werden, welche gleich heissen wie die entsprechende Konfigurationsdatei:

Wenn also eine Konfigurationsdatei beispielsweise `test1.txt` heisst, dann sollte `holdntrade.py test1` innerhalb einer *tmux* Session namens `test1` laufen.

Damit `hades.sh` die *holdntrade*  Instanzen kontinuierlich überwachen kann, muss ein entsprechender *Cronjob* eingerichtet werden:

`*/5 *   *   *   *   /home/bit/trader/hades.sh`



 