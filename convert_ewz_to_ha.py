#!/usr/bin/env python3
"""
Konvertiert einen EWZ Smartmeter-CSV-Export (15-Minuten-Werte) in das
Import-Format der Home-Assistant-Integration "klausj1/homeassistant-statistics"
(Action: import_statistics.import_from_file).

--> https://www.ewz.ch/de/mein-ewz-uebersicht.html

Unterstuetzt zwei Modi:
  --mode sum    Kumulierte sum/state-Spalten. Fuer den ALLERERSTEN Import
                einer neuen/externen Statistik nötig.
  --mode delta  Nur eine delta-Spalte (Verbrauch pro Stunde). Fuer NACHTRAEGE,
                wenn die Statistik in HA bereits existiert - HA rechnet den
                Delta-Wert intern auf den letzten bekannten Stand drauf.
                Erneutes Importieren desselben Zeitraums üBERSCHREIBT die
                bestehenden Stunden-Werte (kein Duplizieren) - man kann also
                bedenkenlos ein paar Tage Überlappung mit importieren, falls
                ewz nachträglich Werte korrigiert.

Optionaler Datumsfilter (--from-date / --to-date oder --last-days), um aus
einem kompletten Monatsexport nur einen Ausschnitt (z.B. die letzten 3 Tage)
zu extrahieren.

Nutzung Beispiele:
    # Erstimport (kompletter Zeitraum, kumuliert)
    python3 convert_ewz_to_ha.py data/XYZ.csv export/import.csv --mode sum

    # Taeglicher Nachtrag: nur die letzten 3 Kalendertage aus dem Monatsexport
    python3 convert_ewz_to_ha.py data/XYZ.csv export/nachtrag.csv --mode delta --last-days 3

    # Nachtrag fuer einen fixen Tag
    python3 convert_ewz_to_ha.py data/XYZ.csv export/nachtrag.csv --mode delta --from-date 2026-08-30 --to-date 2026-08-31


Import HA:
    # Entwicklerwerkezeuge -> Aktion -> Import Statistics from File (upload file to /ewz_import)
    YAML:

action: import_statistics.import_from_file
data:
  decimal: dot ('.')
  datetime_format: '%d.%m.%Y %H:%M'
  filename: ewz_import/nachtrag.csv
  delimiter: ','

"""
import argparse
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

ZURICH = ZoneInfo("Europe/Zurich")


def convert(input_path: str, output_path: str, statistic_id: str, unit: str = "kWh",
            mode: str = "sum", baseline: float = 0.0,
            from_date: date | None = None, to_date: date | None = None) -> pd.DataFrame:
    df = pd.read_csv(input_path, sep="|", encoding="utf-8-sig")
    df = df.rename(columns={"Datum Uhrzeit": "timestamp_raw", "Wert Zeit": "energy_kwh"})
    df["timestamp"] = pd.to_datetime(df["timestamp_raw"], format="%d.%m.%Y %H:%M")
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Zeitstempel = Intervall-ENDE -> 1 Min abziehen, auf volle Stunde abrunden
    df["hour_start"] = (df["timestamp"] - pd.Timedelta(minutes=1)).dt.floor("h")

    # Nicht existierende lokale Stunden (DST-Fruehjahrssprung) auf die
    # vorherige gueltige Stunde zusammenlegen.
    unique_hours = df["hour_start"].unique()
    for h in unique_hours:
        ts = pd.Timestamp(h)
        try:
            ts.tz_localize(ZURICH, nonexistent="raise", ambiguous=True)
        except Exception:
            df.loc[df["hour_start"] == h, "hour_start"] = ts - pd.Timedelta(hours=1)

    # Optionaler Datumsfilter auf den Kalendertag der Stunde (lokale Zeit).
    if from_date is not None:
        df = df[df["hour_start"].dt.date >= from_date]
    if to_date is not None:
        df = df[df["hour_start"].dt.date <= to_date]

    if df.empty:
        raise ValueError("Keine Daten im gewaehlten Zeitraum gefunden - "
                          "Datumsfilter und CSV-Inhalt pruefen.")

    hourly = df.groupby("hour_start", as_index=False)["energy_kwh"].sum().sort_values("hour_start")

    hourly["statistic_id"] = statistic_id
    hourly["unit"] = unit
    hourly["start"] = hourly["hour_start"].dt.strftime("%d.%m.%Y %H:%M")

    if mode == "delta":
        hourly["delta"] = hourly["energy_kwh"].round(6)
        out = hourly[["statistic_id", "start", "unit", "delta"]]
    else:
        hourly["sum"] = (baseline + hourly["energy_kwh"].cumsum()).round(6)
        hourly["state"] = hourly["sum"]
        out = hourly[["statistic_id", "start", "unit", "sum", "state"]]

    out.to_csv(output_path, sep=",", index=False)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input_csv", help="Pfad zum EWZ-Export (15-Min-Werte)")
    parser.add_argument("output_csv", help="Pfad zur Ausgabedatei (fuer HA-Import)")
    parser.add_argument("--statistic-id", default="sensor:ewz_stromverbrauch")
    parser.add_argument("--unit", default="kWh")
    parser.add_argument("--mode", choices=["sum", "delta"], default="delta",
                         help="delta = Nachtrag (Standard), sum = Erstimport")
    parser.add_argument("--baseline", type=float, default=0.0,
                         help="Startwert fuer die Kumulierung bei mode=sum")
    parser.add_argument("--from-date", type=str, default=None,
                         help="Nur Stunden ab diesem Kalendertag (YYYY-MM-DD)")
    parser.add_argument("--to-date", type=str, default=None,
                         help="Nur Stunden bis und mit diesem Kalendertag (YYYY-MM-DD)")
    parser.add_argument("--last-days", type=int, default=None,
                         help="Nur die letzten N Kalendertage der Datei "
                              "(ueberschreibt --from-date/--to-date)")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    to_date = date.fromisoformat(args.to_date) if args.to_date else None

    if args.last_days is not None:
        # letzten Kalendertag der Datei bestimmen, dann N Tage zurueckrechnen
        tmp = pd.read_csv(args.input_csv, sep="|", encoding="utf-8-sig")
        tmp = tmp.rename(columns={"Datum Uhrzeit": "timestamp_raw"})
        last_ts = pd.to_datetime(tmp["timestamp_raw"], format="%d.%m.%Y %H:%M").max()
        last_day = (last_ts - pd.Timedelta(minutes=1)).date()
        from_date = last_day - timedelta(days=args.last_days - 1)
        to_date = last_day

    result = convert(args.input_csv, args.output_csv, args.statistic_id, args.unit,
                      mode=args.mode, baseline=args.baseline,
                      from_date=from_date, to_date=to_date)

    print(f"Zeitraum: {from_date or 'Dateianfang'} bis {to_date or 'Dateiende'}")
    print(f"{len(result)} Stundenwerte geschrieben nach {args.output_csv}")
    print(result.to_string(index=False))
