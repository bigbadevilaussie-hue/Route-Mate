# Route-Mate data inventory (read-only extract of moto.json and audio.json)

Everything below is read directly from the two project files. UNKNOWN means the file does not contain the information. Built-in definitions (def-*) are not stored in the project JSON; they live in `DEFAULT_COMPONENTS` in the repo (`tests/solver/helpers.js`), which was not supplied.

## moto.json

- Board: 24 rows x 56 cols = 1344 holes; lockedRows=True, lockedCols=True; wires=0, cuts=0
- Components: 44 total, 33 on-board, 11 off-board
- Fields present: locked on 0 parts, boardPos non-null on 0, flexibleEndPos on 0, boardExcluded on 0. No edge-constraint field exists. `rotation` is present on every part but is stale while boardPos is null.
- Saved settings: drilledCutsOnly=False, noWireStacking=False, allowStanding=True, v5Effort=4

### Components

| # | label | component id | defId | side | footprint source | w x h | pins | pad coordinates (pin id: name @ row,col) |
|---|---|---|---|---|---|---|---|---|
| 1 | AGM -in | `dca1b808-66df-4287-ade5-52a04fd415e8` | `def-connector-2` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 2 | Kill Switch | `ed42d27c-d226-4ee1-96ea-f3eecc8b7ac5` | `def-switch` | OFF | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 3 | F1 | `658d2bd2-5969-4d69-a065-7fb47f0b9c46` | `def-fuse` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 4 | TVS | `9f972ac1-c5fe-429d-9eaf-eb8af0d194a7` | `def-diode` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 5 | C1 | `867a45fb-f2cc-4ea6-b8fc-71ccd51ee464` | `def-cap-polarized` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 6 | M1 | `8706694e-a1c0-49bd-ab63-30dc6a54cab4` | `custom-44dbe9fa-5d57-4217-8df4-89745367b97f` | on | custom def (project) | 6 x 8 | 4 | 1: 12V @ 0,0; 2: GND @ 0,5; 3: 5V @ 7,0; 4: GND @ 7,5 |
| 7 | Buzzer | `595b5428-47d7-455f-a787-6c7e68c7d9d5` | `def-connector-2` | OFF | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 8 | 12v Mosfet | `ea4eb5c7-9943-44b9-83b1-564438540899` | `def-pmos` | on | override (project) | 1 x 5 | 3 | 1: G @ 1,0; 2: D @ 2,0; 3: S @ 3,0 |
| 9 | R1 | `aab855bd-771e-4b59-8b0e-7df17a61fbc4` | `def-resistor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 10 | R2 | `ef779f52-e4cb-4eb3-b84c-349fba4cddf5` | `def-resistor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 11 | C2 | `b47013c8-ba50-4075-96cb-d819541c39f8` | `def-capacitor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 12 | ESP32 | `9614f865-fc61-4d6f-bd7c-3d66c2a6ba16` | `custom-8b627b44-80a5-45f9-8b8a-5217d839af73` | on | custom def (project) | 6 x 9 | 18 | 1: TX @ 0,0; 2: 5V @ 0,5; 3: RX @ 1,0; 4: GND @ 1,5; 5: GPIO1 @ 2,0; 6: 3V3 @ 2,5; 7: GPIO2 @ 3,0; 8: GPIO13 @ 3,5; 9: GPIO3 @ 4,0; 10: GPIO12 @ 4,5; 11: GPIO4 @ 5,0; 12: GPIO11 @ 5,5; 13: GPIO5 @ 6,0; 14: GPIO10 @ 6,5; 15: GPIO6 @ 7,0; 16: GPIO9 @ 7,5; 17: GPIO7 @ 8,0; 18: GPIO8 @ 8,5 |
| 13 | Q1 | `842487dc-f050-4e09-9f5f-b8bc126abd0d` | `def-npn` | on | override (project) | 1 x 3 | 3 | 3: E @ 0,0; 1: B @ 1,0; 2: C @ 2,0 |
| 14 | D1 | `7f77890b-b930-4ea0-8720-17ef08639a83` | `def-zener` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 15 | R3 | `38aeb30f-be0d-4655-b21d-720b2fc9f3bd` | `def-resistor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 16 | R4 | `7865d1fa-8e62-4e99-92a0-46d42316b6cb` | `def-resistor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 17 | R5 | `463f365f-af11-42a6-99ed-18fff4ea1837` | `def-resistor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 18 | Q2 | `a136cdcf-ce34-4793-8197-51b986e1fbe8` | `def-npn` | on | override (project) | 1 x 3 | 3 | 3: E @ 0,0; 1: B @ 1,0; 2: C @ 2,0 |
| 19 | D2 | `c0c71375-ad9b-424f-9e38-fbbcb31c2e9e` | `def-diode` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 20 | R6 | `53b8bd9f-0a83-4a68-a819-b9b23cea3eee` | `def-resistor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 21 | R7 | `c3127828-24f4-45b2-821d-58ac566e56ec` | `def-resistor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 22 | U2 | `49e180c6-90f1-4cb6-91e3-3fd161e43007` | `custom-82ba25cf-3af7-45d6-be5e-e0854a22427b` | OFF | custom def (project) | 4 x 6 | 4 | 1: VIN @ 5,0; 2: GND @ 5,1; 3: SCL @ 5,2; 4: SDA @ 5,3 |
| 23 | U3 | `d2fb5777-f4e0-49d5-94c1-44df45c9ada9` | `custom-2133d34e-6106-4165-899d-79b03ae339cb` | OFF | custom def (project) | 4 x 1 | 2 | 1: XTAL_P @ 0,0; 2: XTAL_N @ 0,3 |
| 24 | J1 | `de2c5fec-0f89-4c8d-af99-e51f76a90e4c` | `def-connector-2` | OFF | override (project) | 1 x 2 | 2 | 1: GPIO 15 @ 0,0; 2: GPIO 16 @ 1,0 |
| 25 | C3 | `38dd929e-a209-4f7c-a134-bb59069a3884` | `def-capacitor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 26 | C4 | `c7669b59-e3fd-49cd-957d-b2a08ecf8561` | `def-capacitor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 27 | LCD1 | `9d7fb1d9-5d4b-4745-9255-15349239d9f0` | `custom-3aca2896-3437-4ffb-ba07-a1d3e317bf14` | OFF | custom def (project) | 22 x 14 | 8 | 1: GND @ 3,21; 2: VCC @ 4,21; 3: SCL @ 5,21; 4: SDA @ 6,21; 5: RES @ 7,21; 6: DC @ 8,21; 7: CS @ 9,21; 8: BLK @ 10,21 |
| 28 | USB | `8cee7751-5442-4b06-aaff-7af39f032ec3` | `custom-9efc65cf-a2f3-40ec-a6bf-a38ae5684097` | OFF | custom def (project) | 6 x 13 | 2 | 1: IN+ @ 0,0; 2: GND @ 0,5 |
| 29 | D3 | `c74b612a-1b9c-4d81-8af1-e00da64819e4` | `def-led` | OFF | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 30 | R9 | `dd6467e9-dbe3-4b4f-b35c-23d112965327` | `def-resistor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 31 | D4 | `708d0dd8-1f34-4792-9a7e-8ad7726790d6` | `def-led` | OFF | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 32 | R10 | `804f0b96-0f37-4d7d-9e72-376c7548c1bf` | `def-resistor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 33 | R11 | `869bc60a-dd30-490c-aa04-454c5417eecd` | `def-resistor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 34 | Wake | `621de3f1-862c-4942-a727-25dadb315e49` | `def-pushbutton` | OFF | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 35 | Switched Buck | `e5fa3aca-1dde-4251-90a9-984b302e7867` | `custom-44dbe9fa-5d57-4217-8df4-89745367b97f` | on | custom def (project) | 6 x 8 | 4 | 1: 12V @ 0,0; 2: GND @ 0,5; 3: 5V @ 7,0; 4: GND @ 7,5 |
| 36 | MPU | `77c3cebd-3237-48d9-85c5-b0b0dfaec1c9` | `custom-642752f4-fc95-4d5d-b6b2-21aa4b466cc5` | on | custom def (project) | 4 x 8 | 8 | 1: VCC @ 0,0; 2: GND @ 1,0; 3: SCL @ 2,0; 4: SDA @ 3,0; 5: XDA @ 4,0; 6: XCL @ 5,0; 7: ADO @ 6,0; 8: INT @ 7,0 |
| 37 | GPS | `adb3d26e-a0af-4dda-b90e-51b263b6f9a8` | `custom-fd3b91be-3685-42db-acae-7e2ab9735565` | on | custom def (project) | 9 x 13 | 5 | 1: VCC @ 12,2; 2: GND @ 12,3; 3: TXD @ 12,4; 4: RXD @ 12,5; 5: PPS @ 12,6 |
| 38 | 30 mm FAN | `76602e8e-dfb9-423d-9490-6de03ba2a911` | `def-connector-2` | OFF | override (project) | 1 x 2 | 2 | 1: RED + @ 0,0; 2: BLK - @ 1,0 |
| 39 | D5 | `66106e8e-4e8a-464e-842a-1efddd8592ca` | `def-diode` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 40 | D6 | `3a25fe42-7be3-4d26-b43c-eb445eb6a248` | `def-zener` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 41 | L1 | `483e5bfe-7315-4603-9963-f8d468a7e3ca` | `def-inductor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 42 | C5 | `b1ea05d2-f72f-417f-bf97-21783c074db2` | `def-capacitor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 43 | C6 | `82fb4734-57f0-4e44-bb35-bf755280df43` | `def-cap-polarized` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 44 | R12 | `93ef3efc-da8e-4f86-95d5-2ef653887746` | `def-resistor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |

### Nets

| net | total | on-board | off-board |
|---|---|---|---|
| GND | 27 | 20 | 7 |
| net2 | 10 | 9 | 1 |
| 3V3 | 5 | 3 | 2 |
| net27 | 4 | 4 | 0 |
| net3 | 4 | 4 | 0 |
| net4 | 4 | 4 | 0 |
| net6 | 4 | 4 | 0 |
| 12v Switched | 3 | 2 | 1 |
| 5vSwitched | 3 | 2 | 1 |
| net10 | 3 | 2 | 1 |
| net11 | 3 | 2 | 1 |
| net12 | 3 | 1 | 2 |
| net13 | 3 | 1 | 2 |
| net19 | 3 | 2 | 1 |
| net7 | 3 | 2 | 1 |
| net9 | 3 | 3 | 0 |
| 12V | 2 | 1 | 1 |
| 5V | 2 | 2 | 0 |
| net1 | 2 | 1 | 1 |
| net14 | 2 | 1 | 1 |
| net15 | 2 | 1 | 1 |
| net16 | 2 | 1 | 1 |
| net17 | 2 | 1 | 1 |
| net18 | 2 | 1 | 1 |
| net20 | 2 | 1 | 1 |
| net21 | 2 | 1 | 1 |
| net22 | 2 | 2 | 0 |
| net23 | 2 | 1 | 1 |
| net24 | 2 | 2 | 0 |
| net25 | 2 | 2 | 0 |
| net26 | 2 | 2 | 0 |
| net28 | 2 | 2 | 0 |
| net29 | 2 | 2 | 0 |
| net5 | 2 | 2 | 0 |
| net8 | 2 | 2 | 0 |

### Off-board parts: pins and nets

- **Kill Switch** (`def-switch`): 1 -> 12V, 2 -> net1
- **Buzzer** (`def-connector-2`): 1 -> net2, 2 -> net7
- **U2** (`custom-82ba25cf-3af7-45d6-be5e-e0854a22427b`): 1/VIN -> 3V3, 2/GND -> GND, 3/SCL -> net11, 4/SDA -> net10
- **U3** (`custom-2133d34e-6106-4165-899d-79b03ae339cb`): 1/XTAL_P -> net12, 2/XTAL_N -> net13
- **J1** (`def-connector-2`): 1/GPIO 15 -> net12, 2/GPIO 16 -> net13
- **LCD1** (`custom-3aca2896-3437-4ffb-ba07-a1d3e317bf14`): 1/GND -> GND, 2/VCC -> 3V3, 3/SCL -> net14, 4/SDA -> net15, 5/RES -> net16, 6/DC -> net17, 7/CS -> net18, 8/BLK -> net20
- **USB** (`custom-9efc65cf-a2f3-40ec-a6bf-a38ae5684097`): 1/IN+ -> 12v Switched, 2/GND -> GND
- **D3** (`def-led`): 1 -> net21, 2 -> GND
- **D4** (`def-led`): 1 -> net23, 2 -> GND
- **Wake** (`def-pushbutton`): 1 -> net19, 2 -> GND
- **30 mm FAN** (`def-connector-2`): 1/RED + -> 5vSwitched, 2/BLK - -> GND

## audio.json

- Board: 24 rows x 56 cols = 1344 holes; lockedRows=True, lockedCols=True; wires=0, cuts=0
- Components: 19 total, 14 on-board, 5 off-board
- Fields present: locked on 0 parts, boardPos non-null on 0, flexibleEndPos on 0, boardExcluded on 0. No edge-constraint field exists. `rotation` is present on every part but is stale while boardPos is null.
- Saved settings: drilledCutsOnly=None, noWireStacking=None, allowStanding=None, v5Effort=4

### Components

| # | label | component id | defId | side | footprint source | w x h | pins | pad coordinates (pin id: name @ row,col) |
|---|---|---|---|---|---|---|---|---|
| 1 | 5v Buck | `a480b4d9-f8a2-44a2-a9a1-8dce061423d4` | `custom-1fb896a4-e143-411d-87f5-12207fa2e23f` | on | custom def (project) | 6 x 8 | 4 | 1: 12V @ 0,0; 2: GND @ 0,5; 3: 5V @ 7,0; 4: GND @ 7,5 |
| 2 | ESP32 | `f0936ce0-b269-4458-aed1-597266e0cae8` | `custom-76977ebb-04f6-4b5e-b580-951b297313b0` | on | custom def (project) | 10 x 22 | 44 | L0: 3V3 @ 0,0; L1: 3V3 @ 1,0; L2: RST @ 2,0; L3: 4 @ 3,0; L4: 5 @ 4,0; L5: 6 @ 5,0; L6: 7 @ 6,0; L7: 15 @ 7,0; L8: 16 @ 8,0; L9: 17 @ 9,0; L10: 18 @ 10,0; L11: 8 @ 11,0; L12: 3 @ 12,0; L13: 46 @ 13,0; L14: 9 @ 14,0; L15: 10 @ 15,0; L16: 11 @ 16,0; L17: 12 @ 17,0; L18: 13 @ 18,0; L19: 14 @ 19,0; L20: 5Vin @ 20,0; L21: GND @ 21,0; R0: GND @ 21,9; R1: TX @ 20,9; R2: RX @ 19,9; R3: 1 @ 18,9; R4: 2 @ 17,9; R5: 42 @ 16,9; R6: 41 @ 15,9; R7: 40 @ 14,9; R8: 39 @ 13,9; R9: 38 @ 12,9; R10: 37 @ 11,9; R11: 36 @ 10,9; R12: 35 @ 9,9; R13: 0 @ 8,9; R14: 45 @ 7,9; R15: 48 @ 6,9; R16: 47 @ 5,9; R17: 21 @ 4,9; R18: 20 @ 3,9; R19: 19 @ 2,9; R20: GND @ 1,9; R21: GND @ 0,9 |
| 3 | Switch | `63c3bd95-9598-46a3-a383-1aaa13bac150` | `def-connector-2` | OFF | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 4 | F1 | `c397073c-9513-4626-8510-739e2c752dbc` | `def-fuse` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 5 | SH4OT | `fbb4dfff-72c9-4c28-aaea-615d1037269f` | `custom-6d2aa661-9a7e-444c-b981-de2f6b2c0c5e` | OFF | custom def (project) | 4 x 6 | 4 | 1: VIN @ 5,0; 2: GND @ 5,1; 3: SCL @ 5,2; 4: SDA @ 5,3 |
| 6 | C1 | `26bd9fd0-a4c5-4327-a1b6-816769a726b8` | `def-capacitor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 7 | C2 | `c705b4b5-b4ca-4718-8900-41451287e448` | `def-cap-polarized` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 8 | C3 | `b9650efe-7ef5-4fe5-95d7-f7ca0fee3f45` | `def-capacitor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 9 | C4 | `3c5974da-aa30-4de1-91cb-238716cf5bca` | `def-cap-polarized` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 10 | R1 | `38f59d44-9eec-4e00-8cba-1d55364c6450` | `def-resistor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 11 | D1 | `73efdb42-04a5-46ea-ad99-85f0b98739c2` | `def-diode` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 12 | MIC1 | `b121de7a-b8b5-4a74-aecc-ef2713545c5d` | `custom-bec0ee2a-e366-447a-8847-91ddd95fe534` | OFF | custom def (project) | 3 x 4 | 6 | 5: SCK @ 0,0; 4: WS @ 0,1; 3: L/R @ 0,2; 6: SD @ 3,0; 1: VDD @ 3,1; 2: GND @ 3,2 |
| 13 | L1 | `f019ce0a-fdfd-4643-bd88-5151d3e1951f` | `def-inductor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 14 | C6 | `94c0e2f4-26ca-400a-b568-639513cca17d` | `def-capacitor` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 15 | C7 | `7d24e4b4-cbad-402e-a248-955b654775f2` | `def-cap-polarized` | on | built-in: NOT IN PROJECT, geometry UNKNOWN | UNKNOWN | >= 2 | UNKNOWN (pin ids seen in assignments: 1, 2) |
| 16 | BMS | `d5722239-8c24-4d27-8c7c-00be926315c7` | `custom-240bd659-b62a-4707-a2f8-078e98573b8f` | OFF | custom def (project) | 7 x 12 | 8 | 3: D @ 4,0; 4: NTC @ 5,0; 5: G @ 6,0; 6: B+ @ 11,0; 9: b+ @ 11,2; 8: BM @ 11,3; 10: b- @ 11,4; 7: B- @ 11,6 |
| 17 | DISP1 | `c1c7f4ff-0636-406e-b423-7ef51d9d4b59` | `custom-f273095a-80cf-4725-ac66-57513f9242d5` | OFF | custom def (project) | 12 x 9 | 12 | P0: K0 @ 0,0; P1: PSH @ 0,1; P2: TRB @ 0,2; P3: TRA @ 0,3; P4: BLK @ 0,4; P5: CS @ 0,5; P6: DC @ 0,6; P7: RES @ 0,7; P8: SDA @ 0,8; P9: SCL @ 0,9; P10: VDD @ 0,10; P11: GND @ 0,11 |
| 18 | AmpRight | `b091f593-224a-4658-83b6-481f13f8ecb1` | `custom-ac217bf3-dd3b-42cb-80b9-947fc0a2dfed` | on | custom def (project) | 7 x 8 | 7 | 1: LRC @ 7,0; 2: BCLK @ 7,1; 3: DIN @ 7,2; 4: GAIN @ 7,3; 5: SD @ 7,4; 6: GND @ 7,5; 7: VIN @ 7,6 |
| 19 | AmpLeft | `1c5af6cb-725d-4d18-b0a9-bc778e7f8f56` | `custom-ac217bf3-dd3b-42cb-80b9-947fc0a2dfed` | on | custom def (project) | 7 x 8 | 7 | 1: LRC @ 7,0; 2: BCLK @ 7,1; 3: DIN @ 7,2; 4: GAIN @ 7,3; 5: SD @ 7,4; 6: GND @ 7,5; 7: VIN @ 7,6 |

### Nets

| net | total | on-board | off-board |
|---|---|---|---|
| GND | 16 | 11 | 5 |
| net28 | 8 | 8 | 0 |
| 3V3 | 6 | 3 | 3 |
| net2 | 3 | 3 | 0 |
| net23 | 3 | 3 | 0 |
| net6 | 3 | 3 | 0 |
| 5V | 2 | 2 | 0 |
| net1 | 2 | 1 | 1 |
| net11 | 2 | 1 | 1 |
| net12 | 2 | 1 | 1 |
| net13 | 2 | 1 | 1 |
| net14 | 2 | 1 | 1 |
| net15 | 2 | 1 | 1 |
| net16 | 2 | 1 | 1 |
| net17 | 2 | 1 | 1 |
| net18 | 2 | 1 | 1 |
| net19 | 2 | 1 | 1 |
| net20 | 2 | 1 | 1 |
| net21 | 2 | 1 | 1 |
| net22 | 2 | 2 | 0 |
| net24 | 2 | 1 | 1 |
| net26 | 2 | 1 | 1 |
| net27 | 2 | 1 | 1 |
| net3 | 2 | 1 | 1 |
| net4 | 2 | 1 | 1 |
| net5 | 2 | 1 | 1 |
| net7 | 2 | 2 | 0 |
| net8 | 2 | 2 | 0 |
| net9 | 2 | 2 | 0 |

### Off-board parts: pins and nets

- **Switch** (`def-connector-2`): 1 -> net3, 2 -> net4
- **SH4OT** (`custom-6d2aa661-9a7e-444c-b981-de2f6b2c0c5e`): 1/VIN -> 3V3, 2/GND -> GND, 3/SCL -> net11, 4/SDA -> net12
- **MIC1** (`custom-bec0ee2a-e366-447a-8847-91ddd95fe534`): 1/VDD -> 3V3, 2/GND -> GND, 3/L/R -> GND, 4/WS -> net13, 5/SCK -> net14, 6/SD -> net15
- **BMS** (`custom-240bd659-b62a-4707-a2f8-078e98573b8f`): 6/B+ -> net1, 7/B- -> GND
- **DISP1** (`custom-f273095a-80cf-4725-ac66-57513f9242d5`): P0/K0 -> net27, P1/PSH -> net26, P2/TRB -> net24, P3/TRA -> net5, P4/BLK -> net16, P5/CS -> net17, P6/DC -> net18, P7/RES -> net19, P8/SDA -> net20, P9/SCL -> net21, P10/VDD -> 3V3, P11/GND -> GND
