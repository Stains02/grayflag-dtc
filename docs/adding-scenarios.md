# Adding a scenario

Use the page footer (**Add or update a scenario**) or the two commands below. Both do the same thing.

```
grayflag-dtc prepare TRACK --id ID [--name NAME] [--tag TAG] [--obj-name-pat PATTERN] [--cap-prefix PREFIX] [--out-dir DIR]
grayflag-dtc collect ID [--log dcs.log] [--force]
```

- `TRACK` is a `.trk` you recorded or downloaded on that server, or a `.miz`. It is a zip with a `mission` file inside.
- `ID` is a lowercase slug (`pg-redux`). It becomes the dataset file name and is the key for refreshing: preparing the same id again replaces the old data when you collect.
- `prepare` writes `<DCS profile>\Missions\Harvest\<id>.miz` (or `--out-dir`) and registers the scenario as **disabled** in `<data>\servers.json`.
- `prepare` also **removes the mission's own script triggers** (every DO SCRIPT / DO SCRIPT FILE action, which is how the server loads its scripts from its own disk). Nothing but the harvest runs, and there is no script error box. The zones, units and airbases the harvest reads are not scripts and stay. `--keep-scripts` leaves them in.
- Run the `.miz` in DCS single player. The injected trigger fires at mission start, reads the mission's trigger zones, and writes the result to `dcs.log` in numbered `GFDTC|part/total|...` lines.
- `collect` takes the newest complete harvest in the log, checks it, writes `<data>\theaters\<id>.json` and enables the scenario. If the checks report problems (unassigned capture points, no objectives found, ...) the file is still written but the scenario stays disabled until you re-run or pass `--force`. DCS rotates `dcs.log` when it starts, so collect before launching DCS again.

## Zone naming

The harvester expects Grayflag's conventions:

- An **objective** is a quad trigger zone with the property `type = obj`, named `OBJ<lattice letter><number>` (`OBJA16`), with the lattice letter in the property `lat` and the display name in the property `str`.
- A **capture point** is a trigger zone named `CAP` or `CAP-<number>`. Each one belongs to the objective quad that contains its centre.

If a scenario names things differently, say so when preparing:

```
grayflag-dtc prepare TRACK --id x --obj-name-pat "^OBJ(%a*)(%d+)$" --cap-prefix CAP
```

(`--obj-name-pat` is a Lua pattern with two captures: the lattice and the number. The default accepts a zone name without the lattice letter, such as the `OBJ10` typo in the Caucasus mission, and takes the lattice from the zone's `lat` property.) The choices are stored with the scenario, so refreshing it reuses them. Deeper changes (the property names themselves) go in the `harvest_config` object of the scenario's entry in `servers.json`: `obj_type_value`, `lane_key`, `name_key`, `obj_name_pat`, `cap_prefix`, `slot_radius_m`.

The `zone kinds` line printed by `collect` lists every zone `type` found and how many there are; it is the quickest way to see what a new scenario uses.

## What the harvest reads

Objectives and capture points; Grayflag's `base` zones (FARP sites with the objective number at which they open); with positions converted by DCS itself (`coord.LOtoLL`, `land.getHeight`); every airdrome and FARP (`world.getAirbases()`, ships skipped); and which aircraft types have player slots at each airbase, from the mission's client units. See [data-format.md](data-format.md).
