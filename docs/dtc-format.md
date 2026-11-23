# What goes into a DTC

A DTC is a JSON file: `{ "name", "type", "data": { ... } }`. `data` has one section per area of the aircraft, and `data.terrain` names the map. DCS writes and reads these itself; this program starts from a base template per aircraft (`templates/dtc/<aircraft>.dtc`, an export from DCS with the points emptied) and only writes the fields described here. Everything else passes through unchanged.

Sources: the DCS flight manuals and Early Access guides, and ED's own DTC editor scripts under `CoreMods/aircraft/<aircraft>/DTC/` in a DCS install. The tests compare the Apache output with a file exported by DCS itself.

Coordinates in both aircraft's files are **DCS map meters** (`x` north, `y` east) and altitudes are **meters**, not lat/lon and feet. The DTC also carries the terrain name, which this program sets from the scenario's theater (`PersianGulf`, `Syria`); a scenario can override it with `terrain` in its `servers.json` entry.

## AH-64D (`AH-64D_BLK_II`)

**Points.** `data.NAV.Mission_1.Points.CTRLM.POINTS[]`: control measures, written as
`{ "alt": m, "id": 46, "note": "", "num": 51, "text": "LAR", "x": ..., "y": ... }`.

- `id` 46 is the control measure type **EU** (enemy unit): the TSD draws a **red box containing the free text**. (FU, id 24, draws a blue box; other types draw other symbols and not all show the text.)
- `num` runs 51-99 (C51-C99): **49 slots**. C93-C99 can be overwritten by datalink position reports, so 42 are safe if you use the datalink; the program warns above 42.
- `text` is up to 3 letters/digits and is the only identifier a crew sees on the TSD (the cockpit shows type, subtype, free text, MGRS and altitude in feet). `note` only shows in the DTC editor; the program fills it with the capture point name.
- `data.NAV.Mission_1.Points.CTRLM.isEnabled` is set when there are points.
- **FARPs** are control measures too: type `FC` (id **68**, "FARP - Fuel and Ammunition"; `FF` 69 is fuel only, `FM` 70 ammunition only). Every Grayflag FARP has both, so they are written as 68. Airfields that have AH-64D slots in the mission are written as type `AG` (id 62, airfield, general). Both take the slots the capture points and the enemy bases leave free. Which ones are offered, and why, is described in the README.

**Radios.** `data.Radios.InitialRadioSettings.<VHF|UHF|FM1|FM2>` holds what each radio is set to at load: `Mode` 0 means "tuned to preset `Preset`", `Mode` 1 means "manual `Frequency`". When the mode is Preset, DCS takes frequency, modulation and encryption from `data.Presets.COMM[Preset-1].COMMS.<radio>`, so the program copies them from there. The page's single **Tune** box per radio sets all of this: 1-10 tunes that preset; a larger number is a manual MHz. Preset frequencies are `data.Presets.COMM[0..9].COMMS.<radio>.Frequency` (ranges: VHF 108-151.975, UHF 225-399.975, FM 30-87.975).

**Laser codes.** `data.Laser.ChannelsCodes.<A-R without I and O>` is `{ "Four", "Three", "Two", "One" }`, the four digits of the code from first to last. The page shows them as the 4-digit code (1688). DCS limits: first digit 1, 2, 4 or 5 (never 3), second 1-7, third and fourth 1-8.

IFF is deliberately not exposed.

## F-16C (`F-16C_50`)

**Steerpoints.** `data.MPD.NAV_PTS[]`: steerpoints 1-25 (`STPT1`...). Only these can join a route, and **the HSD draws only steerpoints that belong to a route** (plus the one selected). A point's route is its `R1`/`R2`/`R3` flag (a point is in at most one route; the order within a route is the point number). The program puts them all on route 1, so the HSD shows them joined by a line, in nearest-neighbour order. The steerpoint has no label field; the capture point code goes in `note`, which only shows in the DTC editor.

**Destinations.** `data.MPD.DEST[]`: destinations 81-99 (`DEST81`..., `number` 1-19): **19 slots** with a 3-character `text` that the HSD draws as white text. They need no route. The program uses them **only for airfields**: those with F-16 player slots first, then the others, those behind a chosen objective (on the side its lattice has already won) before those ahead of it, nearest first. Capture points never go there: a selection of more than 25 capture points is refused, so the pilot never has to work out which points are steerpoints and which are destinations.

The program sets `MPD.mirror_NAV_PTS` and `MPD.mirror_DEST` to false so DCS does not re-sync the points from the mission.

**Radios.** `data.COMM.COMM1` is the UHF radio (20 preset channels, 225-399.975 MHz) and `COMM2` the VHF radio (30-87.975 FM, 116-155.975 AM). Each channel is `{ "freq": MHz, "modulation": 1 (AM) | 2 (FM) }`; the program sets the modulation from the frequency, so VHF 30.0 is FM.

**Countermeasures.** `data.MPD.CMDS.CMDSProgramSettings.MAN1..MAN6.<Chaff|Flare>` is `{ BurstQuantity, BurstInterval, SalvoQuantity, SalvoInterval }` (quantities 0-99, intervals 0-10 s; 0 = off). The page edits MAN1-MAN6; the AUTO and BYP programs are left as in the template.

## F/A-18C (`FA-18C_hornet`)

**Waypoints.** `data.WYPT.NAV_PTS[]`: `{ "id": "STPT<n>", "wypt_num": n, "x", "y", "alt", "note", "text_note", "R1"/"R2"/"R3", "idOA"..., ... }`, with `x`/`y` in DCS map meters and `alt` in meters. The program writes waypoints 1-58 in nearest-neighbour order; waypoint 59 is left free because it is the default air-to-air waypoint (`NAV_SETTINGS.AA_Waypoint`). The route flags stay false and `NAV_ROUTE` is untouched: no sequences are written. Hornet waypoints have no text label in the cockpit, so the capture point code and name go in `note` (the DTC editor's table) and the code in `text_note` (the editor's map). The terrain name is set in `data.terrain` and `data.WYPT.terrain`, and `mirror_NAV_PTS` is false.

Only the waypoints are written for now. The radios, countermeasure programs, HARM, situational-awareness and the other sections come from the base template (`templates/dtc/fa18c.dtc`, an export from DCS) unchanged.

## Other aircraft

The A-10C II has DTC support in DCS too; it is not implemented yet. Adding an aircraft means a plugin that maps the same point list onto its partitions, plus a base template exported from DCS.
