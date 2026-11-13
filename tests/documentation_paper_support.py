"""Module-owned real publication cache. Stateful command tests must not use this helper.

Only unchanged compiled publications and byte exports are shared. Every returned
publication is a deep copy; captures live in module temporary directories. No
readiness check is patched, and no test case or export-format axis is removed.
"""
from copy import deepcopy


class PaperPublications:
    def __init__(self, root):
        self.root = root
        self.documents = {}
        self.captures = {}
        self.exports = {}
        self.reports = {}

    def document(self, client, route, paper=None):
        from tests.test_documentation_page_setup import _real, command, setup
        key = (route, paper)
        if key not in self.documents:
            before = _real(client, route)
            if before["pageSetupOptions"]["current"] is None:
                self.documents.setdefault((route, None), deepcopy(before["document"]))
            current = before["pageSetupOptions"]["current"]
            desired = setup(before["document"]["documentType"], paper) if paper else None
            if current != desired:
                response = command(client, route, before, desired)
                assert response.status_code == 200, response.text
                before = response.json()
            self.documents[key] = deepcopy(before["document"])
        return deepcopy(self.documents[key])

    def captured(self, client, route, paper=None):
        from tests.test_documentation_page_setup import capture_document
        key = (route, paper)
        if key not in self.captures:
            root = self.root / ("c" + str(len(self.captures)))
            document = capture_document(root, self.document(client, route, paper), route)
            self.captures[key] = (deepcopy(document), root)
        document, root = self.captures[key]
        return deepcopy(document), root

    def export(self, client, route, paper=None, format="pdf"):
        key = (route, paper, format)
        if key not in self.exports:
            from ai_inspector.parts_manual import pdf as parts
            from ai_inspector.operations_manual import exports as operations
            from ai_inspector.specification_sheet import exports as specification
            document, root = self.captured(client, route, paper)
            if route == "parts-manual":
                assert format == "pdf"
                payload = parts.build_manual_pdf_bytes(root, "MMLE-50D", document)
            elif route == "specification-sheet":
                fn = {"pdf": specification.build_specification_pdf_bytes,
                      "fillable": specification.build_specification_fillable_pdf_bytes,
                      "docx": specification.build_specification_docx_bytes}[format]
                payload = fn(document, render_root=root, assembly_number="MMLE-50D")
                if format == "fillable":
                    payload = payload[0]
            else:
                assert format in {"pdf", "docx"}
                fn = operations.build_prototype_pdf_bytes if format == "pdf" else operations.build_prototype_docx_bytes
                payload = fn(root, "MMLE-50D", document)
            self.exports[key] = payload
        return self.exports[key]

    def fit_report(self, client, route, paper=None):
        from tests.test_documentation_page_setup import report_for
        key = (route, paper)
        if key not in self.reports:
            self.reports[key] = report_for(self.root / "fit", self.document(client, route, paper))
        return deepcopy(self.reports[key])
