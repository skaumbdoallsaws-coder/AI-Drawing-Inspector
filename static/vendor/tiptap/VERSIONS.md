# Tiptap vendor bundle

One self-contained ES module for the documentation editor (plan section 5). No front-end build step in the app:
this file is built once, reviewed and checked in.

- Bundle: `tiptap.bundle.js`, 450957 bytes, SHA-256 `c36fd989775f6ed6f6884333bd05d8e4f097b25e256e1e14a42c226f7b83b301`
- Load with `?v=c36fd989775f` (the reviewed SHA-256 prefix).
- Every `@tiptap/*` package: exactly **3.32.0** (released 2026-10-13). 3.33.0 (2026-11-05) was the newest on the
  build day; the newest release at least two weeks old was chosen to limit supply-chain risk.
- Built 2026-11-09 by Claude with esbuild 0.28.2 (MIT), installed with `npm install --ignore-scripts`; no package
  install script ran. esbuild is a build tool only and is not in the bundle.
- After the build, the non-ASCII characters esbuild left in regular-expression literals (dashes, curly quotes
  in input rules) were rewritten as equivalent JavaScript unicode escapes, so the file is pure ASCII
  (`python tools/tiptap_bundle_ascii.py tiptap.bundle.js` writes `tiptap.bundle.ascii.js`, the vendored file).
- Contains no `import`, `require`, `process` or network URL (one ProseMirror documentation link inside an error
  message string). Checked in headless Chromium: Editor with StarterKit, text style, highlight, sub/superscript,
  text align, table and unique-id; HTML paste normalisation drops script, event attributes and images.
- Note for P2a: UniqueID assigned ids to only some nodes of the initial content; assign durable ids explicitly.

## Exports

`BackgroundColor`, `Color`, `Editor`, `Extension`, `FontFamily`, `FontSize`, `Highlight`, `LineHeight`, `Mark`, `Node`, `StarterKit`, `Subscript`, `Superscript`, `Table`, `TableCell`, `TableHeader`, `TableRow`, `TextAlign`, `TextStyle`, `UniqueID`, `generateJSON`, `getSchema`, `getText`, `mergeAttributes`

## Rebuild (reproducible)

```text
mkdir dl && copy package.json dl\          # exact pins; package-lock.json is the resolved tree
npm ci --prefix dl --ignore-scripts --no-audit --no-fund
set NODE_PATH=<abs path>\dl\node_modules
dl\node_modules\@esbuild\win32-x64\esbuild.exe entry.js --bundle --format=esm --platform=browser ^
  --target=es2020 --minify --legal-comments=eof --define:process.env.NODE_ENV="production" ^
  --outfile=tiptap.bundle.js
python tools	iptap_bundle_ascii.py tiptap.bundle.js   # then vendor tiptap.bundle.ascii.js as tiptap.bundle.js
```

## Bundled packages (42, all MIT; licence texts in THIRD_PARTY_NOTICES.txt)

| Package | Version | Licence | LICENSE file SHA-256 |
| --- | --- | --- | --- |
| @tiptap/core | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-blockquote | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-bold | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-code | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-code-block | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-document | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-hard-break | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-heading | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-highlight | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-horizontal-rule | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-italic | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-link | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-list | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-paragraph | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-strike | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-subscript | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-superscript | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-table | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-text | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-text-align | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-text-style | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-underline | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extension-unique-id | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/extensions | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/pm | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| @tiptap/starter-kit | 3.32.0 | MIT | `c96e5ecb55ac5931` |
| linkifyjs | 4.4.0 | MIT | `58e6f3677452cca0` |
| orderedmap | 2.1.1 | MIT | `869c30f368eb0873` |
| prosemirror-commands | 1.7.2 | MIT | `ef0b452ced6304db` |
| prosemirror-dropcursor | 1.8.4 | MIT | `ef0b452ced6304db` |
| prosemirror-gapcursor | 1.4.1 | MIT | `ef0b452ced6304db` |
| prosemirror-history | 1.5.1 | MIT | `ef0b452ced6304db` |
| prosemirror-keymap | 1.2.3 | MIT | `ef0b452ced6304db` |
| prosemirror-model | 1.25.13 | MIT | `ef0b452ced6304db` |
| prosemirror-schema-list | 1.6.0 | MIT | `ef0b452ced6304db` |
| prosemirror-state | 1.4.4 | MIT | `ef0b452ced6304db` |
| prosemirror-tables | 1.8.5 | MIT | `d1d2046ebbe6362f` |
| prosemirror-transform | 1.12.5 | MIT | `ef0b452ced6304db` |
| prosemirror-view | 1.42.9 | MIT | `ef0b452ced6304db` |
| rope-sequence | 1.3.4 | MIT | `530424aebdd0e73f` |
| uuid | 14.0.3 | MIT | `beaa6b04fb82e41d` |
| w3c-keyname | 2.2.8 | MIT | `869c30f368eb0873` |
