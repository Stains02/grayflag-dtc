# Changelog

Versions follow `vMAJOR.MINOR.PATCH`: new servers or aircraft bump the minor number, refreshed mission data or fixes the patch number. The version lives in `grayflag_dtc/__init__.py`; release tags must match it.

## Unreleased

- F-16 and F/A-18C no longer offer helipads that DCS reports as airfields (Germany's "H FRG 40", "H Med GDR 01"...). The Apache still uses them.

## 0.1.1 (2026-11-23)

- App icon (a gray flag over a steerpoint marker): on the exe, in the browser tab and in the page header. `tools/make_icon.py` redraws it.
- A "QRF/supply bases" checkbox for every aircraft (remembered per aircraft; on by default for the Apache only). On the F-16 and F/A-18C the enemy bases become steerpoints/waypoints after the capture points, labelled QRF or SUP in the note.
- The Selected panel breaks the selection down (CPs, QRF/supply, airports, FARPs, total); the F-16 shows steerpoints and destinations separately.

## 0.1.0 (2026-11-23)

- First version. Runs on your PC, serves a web page, writes DTC files into `Saved Games\DCS\DTC`.
- Aircraft: AH-64D (control measures, radios and presets, laser codes) and F-16C (steerpoint route, airfield destinations, radios, chaff/flare programs).
- Aircraft: F/A-18C (waypoints only: 1-58 in nearest-neighbour order).
- Apache: the nearest enemy QRF and supply base per chosen objective (within 25 nm) as EU control measures labelled QRF/SUP; the two nearest open FARPs or Apache-slot airfields per chosen objective as FARP and airfield points.
- Spawn points follow the mission: each dataset records which bases allow dynamic helicopter spawning (read from the mission's warehouses), and only those and bases with Apache slots are offered.
- Servers: Persian Gulf REDUX, Syria COIN, Caucasus, Germany WIP_Modern, Sinai.
- Apache: FARPs as fuel-and-ammo control measures (the two most forward open FARPs per chosen objective).
- F-16C: airfield destinations, those with F-16 slots first and then those behind the chosen objective.
- Advanced: add or refresh a scenario from a track you have flown.
