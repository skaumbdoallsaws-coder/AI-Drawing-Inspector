"""BOM extraction prompt for Qwen VLM."""

BOM_EXTRACTION_PROMPT = '''Look at this engineering drawing. If there is a Bill of Materials (BOM) or Parts List table visible, extract it. Return a JSON object:

{
  "hasBOM": true/false,
  "bomLocation": "where on the drawing (e.g., upper right, separate sheet)",
  "bomItems": [
    {
      "itemNumber": "1",
      "partNumber": "the part number",
      "description": "part description",
      "quantity": 1,
      "material": "if specified in BOM"
    }
  ],
  "totalItems": 0,
  "bomNotes": "any notes about the BOM (e.g., 'items not shown', 'see sheet 2')"
}

If there is NO BOM or Parts List visible, return:
{
  "hasBOM": false,
  "bomLocation": null,
  "bomItems": [],
  "totalItems": 0,
  "bomNotes": "No BOM found - this appears to be a detail/part drawing"
}

Only return valid JSON, no other text.'''
