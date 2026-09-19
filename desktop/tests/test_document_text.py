import io
import unittest
import zipfile
from desktop.runtime.document_text import extract


def archive(name, xml):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as output:
        output.writestr(name, xml)
    return buffer.getvalue()


class DocumentTextTests(unittest.TestCase):
    def test_docx_text_preserves_paragraph_order(self):
        data = archive('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>First</w:t></w:r></w:p><w:p><w:r><w:t>Second</w:t></w:r></w:p></w:document>')
        self.assertEqual(extract(data, 'docx'), 'First\nSecond')

    def test_xml_entities_refused(self):
        data = archive('word/document.xml', '<!DOCTYPE x [<!ENTITY unsafe "expanded">]><x>&unsafe;</x>')
        with self.assertRaises(ValueError):
            extract(data, 'docx')

    def test_sheet_cell_references_preserved(self):
        data = archive('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><c r="B2"><v>42</v></c></worksheet>')
        self.assertIn('B2: 42', extract(data, 'xlsx'))

    def test_slide_text(self):
        data = archive('ppt/slides/slide1.xml', '<slide xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>Assembly</a:t></slide>')
        self.assertIn('Assembly', extract(data, 'pptx'))
