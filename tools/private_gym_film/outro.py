"""Render a standalone APEX approval preview without changing the gym film."""
import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw

from edit import ROOT, OUT, execute, font, probe, transcode


PREVIEW = OUT / 'apex-outro-preview/branded-credit'
SOURCE = Path('C:/Users/might/Downloads/APEX_GYM_Silent_Howling_Logo_Outro.mp4')
FILM = OUT / 'source-frames-revision/APEX-GYM-InspectorPro-Clear-Tour-1080p.mp4'
OUTPUT = PREVIEW / 'APEX-GYM-Built-in-InspectorPro-Outro-Preview.mp4'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    PREVIEW.mkdir(parents=True, exist_ok=True)
    protected = {str(path): digest(path) for path in (SOURCE, FILM)}
    source_frame = PREVIEW / 'apex-brand-source.png'
    # The existing title clip contains a clean version of the user's gold logo.
    transcode(['-ss', '0.6', '-i', SOURCE, '-frames:v', '1', source_frame])

    credit = Image.new('RGBA', (1920, 1080))
    draw = ImageDraw.Draw(credit)
    first, second, third = 'Built in ', 'Inspector', 'Pro'
    regular, bold = font(43), font(43, True)
    first_width = draw.textlength(first, font=regular)
    width = first_width + draw.textlength(second + third, font=bold)
    x = (1920 - width) / 2
    draw.text((x, 933), first, font=regular, fill='#B6BDC3', anchor='ls')
    draw.text((x + first_width, 933), second, font=bold, fill='#F2F3F0', anchor='ls')
    pro_x = x + first_width + draw.textlength(second + third, font=bold) - draw.textlength(third, font=bold)
    draw.text((pro_x, 933), third, font=bold, fill='#71CAF0', anchor='ls')
    credit_path = PREVIEW / 'credit.png'
    credit.save(credit_path)

    graph = (
        '[0:v]scale=3840:2160:flags=lanczos,'
        "zoompan=z='1+0.012*(1-pow(1-min(on/45,1),3))':"
        "x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1920x1080:fps=30,"
        'setsar=1,format=yuv444p[brand];'
        '[1:v]format=rgba,fade=t=in:st=0.85:d=0.65:alpha=1[credit];'
        '[brand][credit]overlay=0:0:shortest=1,'
        'fade=t=in:st=0:d=0.45,fade=t=out:st=4.5:d=0.5,format=yuv420p[out]'
    )
    transcode(['-loop', '1', '-framerate', '30', '-i', source_frame,
               '-loop', '1', '-framerate', '30', '-i', credit_path,
               '-filter_complex_threads', '2', '-filter_complex', graph,
               '-map', '[out]', '-an', '-frames:v', '150', '-r', '30',
               '-c:v', 'libx264', '-threads', '6', '-preset', 'slow', '-crf', '15',
               '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
               '-movflags', '+faststart', '-metadata', 'title=APEX GYM | Built in InspectorPro',
               '-metadata', 'comment=Standalone approval preview; not appended to the gym film.', OUTPUT])
    transcode(['-ss', '2.5', '-i', OUTPUT, '-frames:v', '1', PREVIEW / 'preview.png'])
    transcode(['-i', OUTPUT, '-vf', 'fps=2,scale=480:270,tile=5x2',
               '-frames:v', '1', PREVIEW / 'animation-review.jpg'])
    metadata = probe(OUTPUT)
    video = metadata['streams'][0]
    assert len(metadata['streams']) == 1
    assert (video['width'], video['height']) == (1920, 1080)
    assert video['avg_frame_rate'] == '30/1'
    assert int(video['nb_frames']) == 150
    assert abs(float(metadata['format']['duration']) - 5) < .01
    execute([ROOT / '.runtime/video-tools/ffmpeg.exe', '-v', 'error', '-i', OUTPUT,
             '-f', 'null', '-'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert all(digest(Path(path)) == sha for path, sha in protected.items())
    report = dict(output=str(OUTPUT), duration=5, fps=30, width=1920, height=1080,
                  silentPreview=True, mainFilmUnchanged=True, sourceUnchanged=True,
                  brandSource=str(SOURCE), brandSourceTime=0.6,
                  credit='Built in InspectorPro', creditColors=dict(Inspector='#F2F3F0', Pro='#71CAF0'),
                  decodePassed=True,
                  sourceHashes=protected, mainFilmModified=False)
    (PREVIEW / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
