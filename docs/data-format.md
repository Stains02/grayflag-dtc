# Dataset format

One JSON file per scenario, `data/theaters/<id>.json`, validated by [`schema/dataset.schema.json`](../schema/dataset.schema.json) (the tests check the shipped files against it). The same files can be used on their own for other tools.

```jsonc
{
  "schema": 1, "server_id": "pg-redux", "server_name": "Persian Gulf REDUX", "theater": "PersianGulf",
  "harvested_at": "2026-11-20T18:40:31Z", "source_track": "<track file name>",
  "lanes": ["A", "B", "C", "D"],                      // lattices
  "objectives": [{
    "id": "OBJA16", "lane": "A", "seq": 16,           // objective code = lane + seq = "A16"
    "name": "Lar", "placeholder": false,
    "center": { "lat": 27.6, "lon": 54.3 },
    "cps": [{
      "id": "CAP-12", "name": "Lar Airport",          // "capture point" = the mission gave it no name
      "lat": 27.67, "lon": 54.38, "elev_m": 803.3, "radius_m": 600.8, "shape": "circle",
      "dcs": { "x": 36950.5, "y": -190450.2 }         // DCS map meters: x = north, y = east
    }]
  }],
  "airfields": [{
    "id": 4, "name": "Al Dhafra AFB", "kind": "airdrome",   // or "helipad"
    "lat": 24.2579, "lon": 54.5342, "elev_m": 16, "dcs": { "x": -209935.6, "y": -174592.2 },
    "slots": { "F-16C_50": 12, "A-10C": 4 }                 // player slots here, by DCS type name
  }],
  "farps": [{
    "id": "A Base 1 Jenah", "name": "Jenah FARP", "lane": "A",
    "avail": 13,                                          // opens when objective A13 is the active one (0 = from the start)
    "template": "sixPadFarp", "convoy": false,
    "lat": 27.1, "lon": 54.0, "elev_m": 120.4, "dcs": { "x": 95144.0, "y": -196309.0 }
  }],
  "sites": [{
    "id": "A QRF 3", "kind": "qrf",                         // or "supply": enemy QRF and supply bases
    "name": "Lar Area QRF", "lane": "A", "lim": 17,         // lim: the objective number it belongs to (it sits at or next to it)
    "lat": 27.5, "lon": 54.3, "elev_m": 806.0, "dcs": { "x": 185071.0, "y": -178574.0 }
  }],
  "anomalies": []
}
```

- `lat`/`lon` are WGS84 degrees. `dcs.x`/`dcs.y` are mission-editor map coordinates in meters (x north, y east). DTC files for some aircraft want one and some the other. Elevations are meters above sea level.
- **Objective names are whatever the mission says**, which is what the F10 menu shows. Grayflag reuses names and many are jokes or vague, so use `lane` + `seq` as the key, never the name.
- `placeholder` is true for the unnamed "Alpha/Bravo/Charlie/Delta Objective" objectives (Persian Gulf REDUX has 27 in the UAE/Oman part that was added in the REDUX version).
- `kind: "helipad"` entries are FARPs and helipads. On Syria, DCS also reports about 140 small generated helipad-style strips as airdromes (names like `HS02`, `HMed03`, `HStad04`); the program filters them with `config/airfield_filters.json`.
- `slots` lists aircraft types that have client slots at that airbase in this particular mission. A slot not tied to an airbase id belongs to the nearest airbase within 8 km.
- `farps` come from Grayflag's `base` zones: a helicopter FARP (fuel and ammo) or base site. `avail` is the objective number at which it opens on its lattice; the FARP sits at objective `avail - 1` and opens when that objective is captured, so it is open exactly when the active objective of its lattice is `avail` or higher. Some `base` zones are not helicopter FARPs (enemy bases, fixed-wing bases, spawn points); the program filters them by name with `config/farp_filters.json`. The key is optional: a dataset harvested before FARPs were read has none.
- `sites` come from Grayflag's `qrf` and `supply` zones: enemy QRF and supply bases, usually paired and close together but not always. `lim` is the objective number a site belongs to. (Grayflag's `hrf` zones mark a kind of enemy convoy and are not read.) The key is optional.
- `anomalies` is whatever the harvest could not place (a capture point inside no objective, an objective with no capture points). A scenario with anomalies is not enabled automatically.
