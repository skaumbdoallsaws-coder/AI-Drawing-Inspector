# Facility appearance, scene and decal library: asset tools

These scripts rebuild `static/facility_library/`. They are curation tools, not
part of the running application: the app only reads the committed manifests and
files, and never calls a third-party service when a layout opens.

Downloaded archives are untrusted data. Put each download in its own new folder,
keep these scripts elsewhere, and run Python with `-I`.

1. **Textures (ambientCG, CC0).** Download each package listed under
   `textureSets[].source.package` in `appearances.json` from
   `https://ambientcg.com/get?file=<package>`. Check its SHA-256 against
   `packageSha256`, then extract the `_Color`, `_NormalGL`, `_Roughness` and
   `_AmbientOcclusion` maps into `<extracted>/<assetId>/`.

   ```
   python -I tools/facility_library/process_textures.py <extracted> <work>/textures > <work>/texture_report.json
   ```

   Color sets keep an sRGB color map. Tintable sets (brushed metal, fabric,
   cardboard, paper) get a neutral `detail.jpg` whose median sits near white, so
   the finish color sets the hue. Normal maps are the OpenGL (`NormalGL`)
   variant, which three.js expects.

2. **Scene lighting (Poly Haven, CC0).** Use `https://api.polyhaven.com/files/<id>`
   with a User-Agent that names the tool, as the API terms require. Download the
   `1k` `.hdr` into `static/facility_library/environments/`.

3. **Safety signs (Wikimedia Commons, public domain).** Query the Commons API
   for `File:ISO_7010_<code>.svg` with `prop=imageinfo&iiprop=url|sha1|size|extmetadata`
   and save the JSON as `commons.json`. Then:

   ```
   python -I tools/facility_library/fetch_signs.py <folder with commons.json> <work>/decals
   python -I tools/facility_library/normalize_svgs.py static/facility_library/decals <work>/signs_report.json
   ```

   `fetch_signs.py` keeps only files whose license is public domain or CC0, verifies
   each file's SHA-1, and rejects SVGs with scripts or external references.
   `normalize_svgs.py` adds a viewBox where one is missing, so signs scale
   cleanly when they are rasterized.

4. **Manifests.**

   ```
   python -I tools/facility_library/build_manifests.py static/facility_library <work>
   ```

   This writes `appearances.json`, `scenes.json` and `decals.json` with every
   file's size, SHA-256, source URL, license and modifications.
   `tests/test_facility_appearance_library.py` re-checks those hashes.

5. **Thumbnails.**

   ```
   python tools/facility_library/render_thumbnails.py
   ```

   This renders the app's own thumbnails in headless Chromium with one camera
   and fixed lighting: finishes on a sphere, scenes as two spheres on a floor.
   Until thumbnails exist, the panel draws a sphere from each finish's color and
   texture.

`contact_sheet.py` builds a preview sheet of candidate ambientCG assets, which
is how the textures were chosen.
