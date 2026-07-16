# Floating UI Vendor Record

InspectorPro vendors these browser artifacts so contextual controls work
without network access. Upgrade the files and this record together.

## Packages

| Package | Version | Vendored file | SHA-256 |
| --- | --- | --- | --- |
| `@floating-ui/core` | `1.7.5` | `floating-ui.core.umd.min.js` | `FC0CCA21A6CF2EF0C9C908FBEDE0614DCAF285E8EBFED20D0E144FAFC2EBF059` |
| `@floating-ui/dom` | `1.7.6` | `floating-ui.dom.umd.min.js` | `214B5E019F70FDA36C7F0A35E5EB3AA84FA53448C0F8CAC4F7A4C1E26E71498C` |

## Sources

- `https://unpkg.com/@floating-ui/core@1.7.5/dist/floating-ui.core.umd.min.js`
- `https://unpkg.com/@floating-ui/dom@1.7.6/dist/floating-ui.dom.umd.min.js`
- `https://unpkg.com/@floating-ui/dom@1.7.6/LICENSE`

The license file SHA-256 is
`0E4C9A9B6C71019CBBEA3BDC20B01223110A9035700F9C960C8FCBF78C2325CE`.

## License

Floating UI is licensed under the MIT License. The upstream license text is
retained in `LICENSE` beside the vendored artifacts.

## Compatibility

The DOM UMD build expects the core UMD build to load first and exposes the
`FloatingUIDOM` global. InspectorPro loads both classic scripts before
`floating_surface.js` and `process_map_editor.js`.
