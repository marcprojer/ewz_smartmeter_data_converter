# EWZ Smartmeter Data Converter

Dieses Projekt konvertiert EWZ Smartmeter-CSV-Exportdaten in ein Import-Format für Home Assistant.

## Zweck

Die Datei `convert_ewz_to_ha.py` liest einen EWZ-Export ein und erzeugt eine CSV-Datei, die für den Import von Statistiken in Home Assistant genutzt werden kann.

## Nutzung

```bash
python3 convert_ewz_to_ha.py data/XYZ.csv export/nachtrag.csv --mode delta --last-days 3
```

Weitere Beispiele und Optionen sind in der Skript-Docstring im Code zu finden.

## Hinweis

Diese Readme wurde mit Hilfe von KI verfasst.
