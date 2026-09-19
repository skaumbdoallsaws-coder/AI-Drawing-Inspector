# Facility Asset Manufacturer Specification Research

Research date: 2026-09-09. Scope: manufacturing-related equipment in the local asset library, including automation, fixtures, and material handling.

This is a research note, not an imported capability catalog. No layout, asset definition, motion profile, or operational limit was changed. Manufacturer specifications below describe a named product or product family; they are not yet revision-bound to the local CAD assets. Model year, configuration, and nameplate confirmation remain necessary.

## 1. Manufacturer References Found

### Haas ST-30 CNC Lathe

- Current standard model: 254 mm chuck, 76 mm bar capacity, 3,400 rpm maximum spindle speed, and 22.4 kW maximum spindle rating.
- Maximum cutting length: 826 mm, dependent on workholding. Maximum cutting diameter is 381 mm with the BOT turret or 349 mm with BMT65.
- Match status: model name matches; CAD generation and turret configuration are unconfirmed. The manufacturer page explicitly distinguishes current and previous machines, so current specifications must not silently replace older-generation data.

Source: [Haas ST-30 product specifications](https://www.haascnc.com/machines/lathes/st/models/standard/st-30.html).

### Doosan / DN Solutions DBC 130 II

- X/Y/Z travel: 3,000 / 2,000 / 1,600 mm.
- Table: 1,800 x 1,600 mm; maximum workpiece weight: 15,000 kg.
- Listed machine weight: 43,000 kg.
- Match status: model name matches the DN Solutions listing. Year, regional configuration, installation envelope, and options remain unconfirmed. The web page has a malformed metric spindle-power row, so that field was not transcribed.

Source: [DN Solutions DBC 130 II](https://www.dn-solutions.com/global/product/nc-boring/boring/dbc-130-ii.do).

### ACER Dynamic 1760G Lathe

- The original Dynamic G-series brochure lists a 17-inch swing, 60-inch distance between centers, and 2.25-inch spindle bore for this size.
- Series spindle-speed range: 50-1,800 rpm, with 12 steps.
- Match status: probable model match; confirm the machine is the geared Dynamic 1760G, not the distinct variable-speed e-Lathe 1760G. No reseller-only power, mass, or footprint values were adopted.

Sources: [ACER Dynamic engine-lathe catalog](https://aceronline.net/product-category/machines/engine-lathes/dynamic/), [original ACER brochure, archived by Exact Machine Service](https://www.exactmachineservice.com/assets/pdfs/acer-dynamic-elathe-brochure.pdf).

### ABB IRB 6650 Robot

The archived ABB specification lists two relevant variants:

| Variant | Rated handling capacity | Reach |
| --- | --- | --- |
| IRB 6650-125/3.2 | 125 kg | 3.2 m |
| IRB 6650-200/2.75 | 200 kg | 2.75 m |

The local name does not identify which variant is represented. Do not assign either capacity or reach to the asset until its variant is confirmed. These values do not establish tooling allowance, permissible load distribution, task reachability, or collision-free robot motion.

Source: [ABB product specification 3HAC023933-001, revision 1, printed page 7](https://library.e.abb.com/public/560fa420555c2d8ac1257b4b0052112c/3HAC023933-001_rev1_en.pdf).

### Catalog Label: ADTECH SA6-1440H Robot

- STEP's official SA6/1440H listing specifies 6 kg maximum load, 1,475 mm maximum reach, and +/-0.05 mm repeatability.
- Match status: model-number match with a branding discrepancy. The library says ADTECH; the primary product page is STEP. Review the CAD source and nameplate before binding these specifications.

Source: [STEP SA6/1440H product page](https://www.stepelectric.com/Product_detail/79.html).

### Nordson EFD E6 Dispensing Robot

- Local description identifies the otherwise generic "Nordson EFD 3-Axis Robot" as an E6.
- Legacy E6 working area: 620 x 500 x 150 mm.
- Maximum X/Y speed: 800 mm/s; Z: 320 mm/s.
- Archived data sheet lists 10 kg workpiece payload and 5 kg tool payload. These are distinct limits.
- Match status: legacy model reference found. Current E-series pages emphasize other sizes; do not substitute E5 specifications for E6.

Sources: [Nordson official E-series operating manual, legacy-model dimensions](https://nc-p-001.sitecorecontenthub.cloud/api/public/content/14213763a5ac49e28453f22d2b805662?v=7ce1f9c2), [original Nordson EFD data sheet, archived by Flumasys](https://flumasys.s27.cdn-upgates.com/s/s6929a2b9bcd5f-nordson-efd-e-series-data-sheet.pdf).

### MMLE-50D Mobile Lift

- Rated capacity: 1,100 lb (approximately 499 kg).
- Platform: 20.5 x 39.8 inches.
- Lowered/raised platform heights: 19.5 / 63.5 inches; vertical travel: 44 inches.
- Battery-powered lifting does not establish powered travel, autonomous navigation, or a forklift operating profile.
- Match status: manufacturer model match. Confirm configuration against the local asset before using these as constraints.

Source: [Lift Products Maxx-Mobile electric lift carts](https://www.liftproducts.com/liftcarts/mmle.html).

### Carr Lane CL-400-PTPB Tooling Plate

- Blank square pallet tooling plate: 400 mm square, 50 mm thick.
- Material: gray cast iron, ASTM Class 45; four mounting holes.
- This is workholding equipment, not a processing machine. Plate mass must not be interpreted as load capacity.
- Match status: exact catalog-number reference found; local CAD revision remains unverified.

Source: [Carr Lane CL-400-PTPB](https://www.carrlane.com/product/jig-fixture/blank-tooling-plates/square-pallet-tooling-plates-blank/square-pallet-tooling-plates-blank-400mm/cl-400-ptpb).

## 2. Partial Matches and Unresolved Identities

| Local asset | Research result | Still needed |
| --- | --- | --- |
| Mori CL-200A CNC Lathe | No exact OEM machine specification sheet was verified in this search. | Mori Seiki model/year and original manual. |
| Hardinge HLV Lathe | An original [Hardinge HLV brochure](https://pdf.directindustry.com/pdf/hardinge-bridgeport/hlv-manual-toolroom-lathe/7287-62922.html) was located, but the local label does not resolve generation or HLV/H variants. | Variant and original specification-page verification before assigning numerical limits. |
| Kalamazoo H9AW Horizontal Band Saw | An archived Clausing/Kalamazoo brochure containing H9AW was located, but its complete capacity table was not verified. | Original H9AW manual, machine year, motor and electrical configuration. |
| FANUC 14tes2 Robot | No authoritative FANUC model specification was verified for this identifier. | Actual robot model and controller from the source assembly or nameplate. |
| JMP 875 Bottle Filler | A [CAD contributor listing](https://www.3dcontentcentral.com/download-model.aspx?catalogid=171&id=363932&partnumber=JMP+875) confirms the label, not a verified OEM throughput specification. | Manufacturer, model, filling technology, container range, and cycle data. |
| LNS QLS-LF Bar Loader | Its [original CAD listing](https://www.3dcontentcentral.com/download-model.aspx?catalogid=171&id=225592) describes an approximate floor-layout model. | Actual LNS model and configuration; do not derive bar capacity from approximate geometry. |
| RTMX Raised | Lift Products documents a Roto-Max RTMX family with several capacities. | Exact RTMX suffix. |
| MC-10-M FLS | Lift Products documents MC-10-M as a powered platform-truck model; the FLS configuration was not verified. | Confirm manufacturer and suffix against CAD provenance. |
| JRMC-11S | Related JRMC-11 variants appear in the manufacturer catalog, but the exact local suffix is unresolved. | Exact variant/nameplate. |
| MCJR-11-MR | Possible relationship to the JRMC family is an inference, not a confirmed identification. | Original supplier record. |
| 1D601 Industrial Machine | No authoritative model specification was verified. | Manufacturer and unambiguous model designation. |
| P40ft Assembly / Kittempo Duo | Names do not establish a verified manufacturing capability. | Product identity and intended function. |

Source for the RTMX, MC-10-M, and JRMC family comparisons: [Lift Products manufacturer catalog](https://www.liftproducts.com/pdf/lift-products-catalog.pdf). Family similarity is not sufficient evidence to import a capacity or travel profile.

## 3. Generic Assets Cannot Yet Receive Model-Specific Specifications

These library entries lack enough identity information for a defensible manufacturer-specification match:

| Group | Assets | Examples of missing specifications |
| --- | --- | --- |
| Machining and thermal processing | CNC Milling Machine; Three-Axis CNC Machine; CNC Lathe; Okamoto Surface Grinder; Sinker EDM Machine; Vertical Band Saw; Woodworking Jointer; Industrial Oven | Exact model, work envelope, power, tooling, temperature/process range, utilities. |
| Testing | Electrical Glove Test Bath; Electrical Test Tank | Manufacturer, rated voltage, test method, measurement limits. Existing unverified-use labels remain applicable. |
| Workstations | Assembled Laboratory Workstation; Assembly Workbench and dimensional variants; Mobile Folding Worktable | Rated load, attached tools, actual process capability. A bench alone does not establish inspection capability. |
| Lifting | 30 x 96 Lift Table; Centralizing Jack; Winch Model; 2 Ton Crane; 8 Ton Crane; Crane; Crane and Hoist Assembly | Certified model, lift range, load chart, configuration and duty rating. Names are not verified ratings. |
| Industrial vehicles | Electric Forklift; Compact Green Forklift; Red Telescopic Forklift; Reversible-Fork Lift Truck; Pallet Truck; All-Terrain Pallet Truck | Exact model, attachments, load center, turning radius, speed/reverse limits and load chart. |
| Conveyors | 400 x 1540 Modular Conveyor; Curved Modular Belt Conveyor; NA300x2100; NA450x1200; Conveyor Roller Guide | Manufacturer, belt/roller configuration, speed, drive, rated distributed and concentrated loads. |
| Carts and storage | Mobile Utility Cart; Steel Flush Platform Truck; TR1631 Mobile Mesh Roll Container; Wood Storage Cart; Pallet Rack | Manufacturer, configuration, load rating and any powered-drive capability. |

Dimensions embedded in an asset name or measured from CAD are geometry evidence only. They do not establish process capacity, rated load, operating clearance, or safety compliance.

## 4. Requirements Before Sage Can Use These as Constraints

1. Bind the document to the exact manufacturer, model, variant, year/configuration, asset ID, and asset revision.
2. Preserve the source document, its revision/date, units, applicable options, and field-level provenance. Distinguish nominal, maximum, continuous, peak, and configuration-dependent ratings.
3. Separate physical dimensions, work envelope, installation/service envelope, tooling allowance, and transport dimensions.
4. Keep unresolved fields explicitly unknown. Do not convert missing performance evidence into inferred cycle times, throughput, load limits, safety clearance, or motion authority.
5. Review a small first batch of model-identified equipment before expanding to generic assets. Existing validators and published-profile requirements continue to apply.

Finding a data sheet does not itself make a static CAD asset articulated, a route collision-free, or a manufacturing process production-ready.
