"""Bounded, read-only text previews of OpenXML output documents."""
import io
import sys
import zipfile
import xml.etree.ElementTree as ET
import re


class NoDTD(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError('Document types are not allowed')


def natural_key(name):
    return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', name)]


def extract(data, kind):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        if len(names) > 4096:
            raise ValueError('Too many archive entries')
        if sum(info.file_size for info in archive.infolist() if info.filename.endswith('.xml')) > 16 * 1024 * 1024:
            raise ValueError('Document XML budget exceeded')
        def xml(name):
            info = archive.getinfo(name)
            if info.file_size > 8 * 1024 * 1024:
                raise ValueError('XML member too large')
            content = archive.read(name)
            if b'<!DOCTYPE' in content or b'<!ENTITY' in content:
                raise ValueError('XML entities are not allowed')
            return ET.fromstring(content, parser=ET.XMLParser(target=NoDTD()))
        result = []
        if kind == 'docx':
            root = xml('word/document.xml')
            for paragraph in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                result.append(''.join(node.text or '' for node in paragraph.iter() if node.tag.endswith('}t')))
        elif kind == 'pptx':
            slides = sorted((name for name in names if name.startswith('ppt/slides/slide') and name.endswith('.xml')), key=natural_key)
            for name in slides:
                result.append(name.rsplit('/', 1)[-1])
                result.extend(node.text or '' for node in xml(name).iter() if node.tag.endswith('}t'))
        elif kind == 'xlsx':
            shared = []
            if 'xl/sharedStrings.xml' in names:
                shared = [''.join(t.text or '' for t in item.iter() if t.tag.endswith('}t')) for item in xml('xl/sharedStrings.xml')]
            for name in sorted((n for n in names if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')), key=natural_key):
                result.append(name.rsplit('/', 1)[-1])
                for cell in xml(name).iter():
                    if not cell.tag.endswith('}c'):
                        continue
                    values = [n.text or '' for n in cell.iter() if n.tag.endswith(('}v', '}t'))]
                    value = ' '.join(values)
                    if cell.get('t') == 's' and value.isdigit():
                        value = shared[int(value)]
                    result.append(cell.get('r', '') + ': ' + value)
        else:
            raise ValueError('Unsupported document type')
        text = '\n'.join(result)
        if len(text) > 1_000_000:
            raise ValueError('Text preview too large')
        return text


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    data = sys.stdin.buffer.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise ValueError('Document too large')
    print(extract(data, sys.argv[1]))
