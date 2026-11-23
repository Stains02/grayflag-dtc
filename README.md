# grayflag-dtc

Pick the active objectives on a Grayflag server, press a button, and get a native DCS **DTC** file in your cockpit's data-cartridge list: every capture point as a steerpoint or control measure, labelled with a short code, plus your radios, presets, laser codes and countermeasure programs.

It is one program that runs on the PC you fly DCS on. It serves a web page on `localhost`; nothing leaves your machine.

| Aircraft | What you get |
| --- | --- |
| **AH-64D** | Capture points as enemy-unit control measures (red box with a 3-character label on the TSD), C51 onward, then the nearest enemy QRF and supply bases (red boxes labelled QRF and SUP), then the FARPs most likely to be open and closest to the front, as fuel-and-ammo FARP points. Radios, 10 presets, 16 laser codes. |
| **F/A-18C** | Capture points as waypoints 1-58 (waypoint 59 stays free: it is the default air-to-air waypoint). Waypoints only for now: radios, countermeasures and the rest come from the base DTC unchanged. |
| **F-16C** | Up to 25 capture points as a steerpoint route (NAV 1-25, route 1, so they show on the HSD). The destinations (81-99) hold airfields, labelled: the ones with F-16 slots first, then the nearest. Radios (COM1/COM2) and chaff/flare programs. |

Scenarios included: **Persian Gulf REDUX**, **Syria COIN**, **Caucasus**, **Germany WIP_Modern** and **Sinai**. See [Versions and updates](#versions-and-updates).

## Note on AI Usage
This program was vibe coded by Stains02 using Claude. The end product is an exe file that runs code on your computer. This program does not receive any data beyond the inputs you give it in the browser and it does not send any data to programs on your computer or to the internet. All source code is available here for review, and you are free to take/modify it as you please.

## Use it

1. Download `grayflag-dtc.exe` from the [Releases](../../releases) page and double-click it. A console window opens and your browser goes to `http://127.0.0.1:8765/`. Close the window to quit.
2. Choose the server and the aircraft. Pick the objectives that are active on each lattice (click them, or type `A16 B21 D31` in the quick entry box). Each objective card shows the capture point names it contains, which is how you tell Grayflag's repeated objective names apart.
3. Check the preview, open **Radios** and the other settings if you want to change anything (press **Save as defaults** to keep your choices; **Reset** returns to the Grayflag comms plan).
4. Press **Send to DCS**. The file is written to `Saved Games\DCS\DTC` as `GF_<server>_<objectives>_<date>.dtc`. (Only the 10 newest `GF_` files are kept. Anything else in that folder is never touched.) **Download DTC** saves the same file wherever you like.
5. In the cockpit, pick the file in the DTC list and load it.

If you have several DCS profiles (`DCS`, `DCS.openbeta`, ...) the program picks the most recently used one. You can change it in the footer of the page.

The exe keeps its datasets and your saved settings in `%LOCALAPPDATA%\grayflag-dtc\data`, so the exe can live on your desktop or in Downloads. Delete that folder to start fresh. (For a portable copy, create a folder named `data` next to the exe before the first run and it will be used instead, e.g. on a USB stick.)

## Which FARPs and airfields are offered

The program cannot see the campaign, but you tell it where each lattice stands by picking the active objective. Grayflag lattices advance in a fixed order and direction, and FARPs unlock along them as objectives fall, so the FARPs behind the active objective are where helicopters are most likely to spawn.

- **Spawn points (Apache):** for each objective you pick, the two nearest places a helicopter can start, behind the front first: FARPs that are open and that helicopters can spawn at (the mission's dynamic-spawn bases with Apache stock), and airfields or helipads that have AH-64D slots. A FARP that unlocks at objective N is open once the active objective of its lattice is N or later; start FARPs (unlock 0) serve every lattice, and a FARP of another lattice counts if you picked an objective there that has reached it. The nearest one is always shown, the second only if it is within 60 nautical miles.  Airfield markers that nobody can spawn at (and enemy bases) are left out. The capture points always get their slots first; the page lists any point that got no slot.
- **Airfields (F-16):** destinations 81-99. First every airfield that has F-16 slots, then the others, those behind a chosen objective before those ahead of it, nearest first.

- **Enemy QRF and supply bases (Apache):** for each objective you pick, the nearest QRF base and the nearest supply base, as enemy control measures labelled `QRF` and `SUP`, unless they are more than 25 nautical miles away or the front has already passed them (each base belongs to an objective number on its lattice; once the active objective is past it, it no longer matters). QRF and supply bases are usually paired and close together, but not always, so each is picked on its own. Capture points come first, then these, then FARPs.

## What the codes are

Every capture point gets a short label (up to 3 letters/digits) built from its in-game name, so what you see in the cockpit (for aicraft that display IDs) is roughly what you saw in the F10 map menu: `Lar Airport` becomes `LAR`, `Southeast` becomes `SE`. Capture points the mission does not name ("capture point") get a prefix built from their objective. Two capture points in different objectives can share a code; within one objective they are unique. Objectives with no real name (the "Alpha/Bravo/Delta Objective" placeholders in Persian Gulf REDUX) show as `A01`, `B05` and so on.

You can override any code: see [Customising](#customising).

## Versions and updates

Releases are numbered `vMAJOR.MINOR.PATCH` (see [CHANGELOG.md](CHANGELOG.md)): a new server or aircraft is a minor release, refreshed mission data or a fix is a patch release. The version is shown at the bottom of the page and with `grayflag-dtc --version`; each dataset shows the date it was read from the mission.

**I intend to keep this updated with new Grayflag servers and with every aircraft that supports DTC.** The [advanced harvest tool](#advanced-adding-a-scenario-yourself) is there in case I am too slow (or no longer around): it lets anyone add or refresh a scenario from a track without waiting for me.

## Customising

Everything lives in the data folder:

| File | Purpose |
| --- | --- |
| `codes/<id>.overrides.json` | `{"CAP-12": "LAR"}`: force the code of a capture point (by its zone name). |
| `codes/<id>.airfields.json` | `{"Al Minhad AFB": "MIN"}`: force an airfield's code. |
| `names/<id>.json` | `{"A16": "My name"}`: change how an objective is named on the page. |
| `settings/<aircraft>.json` | Your saved defaults (written by **Save as defaults**). |
| `servers.json` | Scenarios you added. |

`config/airfield_filters.json` (inside the exe, or in the source tree) lists name patterns for "airfields" that are really helipads and are never offered. Syria's map reports about 140 small generated helipad strips (hospitals, stadiums, oil sites) as airdromes.

## Run from source

```
pip install -r requirements.txt
python -m grayflag_dtc            # same as the exe
python -m grayflag_dtc build pg-redux f16c A16 C1 --out test.dtc      # one DTC, no web page
python -m pytest                  # needs `pip install -r requirements-dev.txt` (and lua5.1 for the harvest tests)
```

Build the exe (Windows): `pip install -r requirements-dev.txt` then `pyinstaller grayflag-dtc.spec`; the result is `dist\grayflag-dtc.exe`. CI does the same on every push and attaches the exe to releases for tags that start with `v`.

## Advanced: adding a scenario yourself

You should never need this: new servers and changed missions arrive as new releases. It exists for the case where updates are slow or have stopped. Grayflag's missions are read out of a track you have flown, using DCS itself, so positions and elevations are exact. It takes a couple of minutes.

At the bottom of the page, open **Advanced: add a scenario from a track**:

1. Pick a track you have flown on that server (from `Saved Games\DCS\Tracks`). Give the scenario an id, a name and a short tag, then **Prepare mission**. This writes `Saved Games\DCS\Missions\Harvest\<id>.miz`: the same mission with a small script added that runs when the mission starts.
2. In DCS, run that mission in single player (any aircraft). Grayflag's own scripts are removed from this copy, so nothing else runs and there is no script error box. Wait until the mission has started.
3. Press **Collect results**. The program reads the script's output from `dcs.log`, checks it, and adds the scenario to the server list.

The same steps from a command prompt:

```
grayflag-dtc prepare "C:\...\Tracks\Multiplayer\<track>.trk" --id my-scenario --name "My Scenario" --tag MS
(run the mission in DCS)
grayflag-dtc collect my-scenario
```

Typing an existing id refreshes that scenario. (`--keep-scripts` keeps the server's own scripts in the prepared mission; you should not need it.) See [docs/adding-scenarios.md](docs/adding-scenarios.md) for scenarios whose zones are named differently, and [docs/data-format.md](docs/data-format.md) for what the harvest produces.

## How it works, and adding an aircraft

- [docs/dtc-format.md](docs/dtc-format.md): what is in a DTC file and how this program fills it in, per aircraft.
- Each aircraft is one module in `grayflag_dtc/airframes/` (a `PLUGIN` with `build`, `validate` and `settings_schema`), one `config/airframes/<id>.json`, and one base template in `templates/dtc/`. The core picks and orders the points, generates the codes and the airfield list; a plugin only writes them into its own aircraft's file.

## Notes

- The DTC files are the native format DCS itself writes and reads. The program only changes the points, the radios/presets/laser codes/countermeasures you can see in its settings, and the terrain name; everything else in the base template passes through untouched.
- Grayflag is a community server; this is an independent tool and is not affiliated with Eagle Dynamics. The shipped datasets were read from Grayflag's missions and are published with the permission of Grayflag management.
- Licence: [MIT](LICENSE).
