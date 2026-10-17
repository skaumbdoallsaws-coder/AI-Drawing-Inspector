"""Reproducible local edit of the recorded Private Gym walkthrough."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from scipy import signal
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/apex-gym-film-20261013'
SOURCE = Path('C:/Users/might/OneDrive/Desktop/idea well/footage3.mp4')
MUSIC = SOURCE.with_name("Eminem - You Don't Know (Instrumental).mp3")
FFMPEG = ROOT / '.runtime/video-tools/ffmpeg.exe'
FFPROBE = ROOT / '.runtime/video-tools/ffprobe.exe'

# Source in/out points are seconds in the user's original recording.
SHOTS = [
    ('01-plan', 132.5, None, 2.8, 'THE COMPLETE CAMPUS', 'APEX GYM', 'A fitness campus designed in InspectorPro.'),
    ('02-reveal', 144, 170, 5.6, 'THE COMPLETE CAMPUS', 'See the whole idea come together.', ''),
    ('03-reception', 171.5, None, 2.8, 'STEP INSIDE', 'From the master plan to the front door.', ''),
    ('04-training', 174, 198, 4.2, 'TRAINING FLOOR', 'Built around the way you train.', ''),
    ('05-strength', 275, 298, 4.2, 'TRAINING FLOOR', 'Built around the way you train.', ''),
    ('06-equipment', 303.5, None, 2.8, 'TRAINING FLOOR', 'Real equipment. Deliberate placement.', ''),
    ('07-warriors', 361, 369, 4.2, 'HALL OF WARRIORS', 'A space with its own identity.', ''),
    ('08-office', 340.3, None, 2.8, 'PRIVATE OFFICE', 'More than a training floor.', ''),
    ('09-conference', 355.5, None, 2.8, 'MEETING ROOM', 'More than a training floor.', ''),
    ('10-lounge', 370, 388, 4.2, 'SOCIAL LOUNGE', 'Work. Play. Unwind.', ''),
    ('11-games', 396, 408, 2.8, 'SOCIAL LOUNGE', 'Work. Play. Unwind.', ''),
    ('12-kitchen', 416, 430, 4.2, 'KITCHEN & CAFE', 'Make room for the everyday moments.', ''),
    ('13-cafe', 438.5, None, 2.8, 'KITCHEN & CAFE', 'Make room for the everyday moments.', ''),
    ('14-recovery', 213.5, 222, 2.8, 'RECOVERY ROOM', 'Room to recharge.', ''),
    ('15-pool', 493, 512, 4.2, 'POOL & JACUZZI', 'Room to recharge.', ''),
    ('16-wellness-flight', 514, 538, 4.2, 'ONE CONNECTED CAMPUS', 'Explore how the spaces connect.', ''),
    ('17-boxing', 540, 549, 2.8, 'BOXING STUDIO', 'Built for every kind of training.', ''),
    ('18-bags', 549, 557, 2.8, 'BOXING STUDIO', 'Built for every kind of training.', ''),
    ('19-basketball', 558, 580, 4.2, 'BASKETBALL COURT', 'From the training floor to the court.', ''),
    ('20-sports-flight', 585, 611, 5.6, 'COURTS & FIELDS', 'Follow the space, not just the floor plan.', ''),
    ('21-soccer', 612, 629, 4.2, 'SOCCER ARENA', 'A bigger picture of what is possible.', ''),
    ('22-outdoor', 641, 658, 4.2, 'OUTDOOR TRAINING', 'Take training outside.', ''),
    ('23-turf', 658, 674, 4.2, 'OUTDOOR TRAINING', 'Take training outside.', ''),
    ('24-calisthenics', 675, 686, 4.2, 'CALISTHENICS', 'Space to push further.', ''),
    ('25-patio', 705.3, None, 2.8, 'BARBECUE PATIO', 'A place to stay after training.', ''),
    ('26-pullback', 706, 723, 5.6, 'APEX GYM', 'Plan the space. Experience it.', ''),
    ('27-close', 723, None, 2.8, 'BUILT IN INSPECTORPRO', 'Your space. Your vision.', 'Facility layout and immersive walkthroughs.'),
]


def probe(path):
    result = execute([FFPROBE, '-v', 'error', '-show_streams', '-show_format',
                      '-of', 'json', path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return json.loads(result.stdout)


def transcode(args):
    try:
        execute([FFMPEG, '-hide_banner', '-nostdin', '-loglevel', 'error', '-y', *args],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as error:
        print(error.stderr.decode('utf-8', errors='replace'), flush=True)
        raise


def font(size, bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf' if bold else
                              'C:/Windows/Fonts/segoeui.ttf', size)


def panel(shot):
    name, _, _, _, label, headline, description = shot
    path = OUT / 'panels' / f'{name}.png'
    path.parent.mkdir(exist_ok=True)
    canvas = Image.new('RGB', (1920, 158), '#101416')
    draw = ImageDraw.Draw(canvas)
    draw.line((0, 0, 1920, 0), fill='#303537', width=2)
    draw.rectangle((46, 28, 79, 31), fill='#C99B39')
    draw.text((94, 15), label, font=font(19, True), fill='#C99B39')
    size = 41
    while draw.textlength(headline, font=font(size, True)) > 1370:
        size -= 1
    draw.text((44, 48), headline, font=font(size, True), fill='#F3F4F2')
    if description:
        draw.text((46, 110), description, font=font(21), fill='#A9B1B4')
    draw.line((1510, 39, 1510, 119), fill='#384044', width=1)
    draw.text((1575, 46), 'InspectorPro', font=font(34, True), fill='#F3F4F2')
    draw.text((1578, 98), 'FACILITY LAYOUT', font=font(17), fill='#C99B39')
    canvas.save(path)
    return path


def render_shot(shot):
    name, start, end, duration, *_ = shot
    path = OUT / 'clips' / f'{name}.mp4'
    path.parent.mkdir(exist_ok=True)
    footer = panel(shot)
    frames = round(duration * 30)
    source_frames = None
    smoothing = 'static detail'
    if end is None:
        still = OUT / 'clips' / f'{name}.png'
        transcode(['-ss', start, '-i', SOURCE, '-frames:v', '1', '-vf',
                   'crop=1800:864:60:52', still])
        inputs = ['-loop', '1', '-framerate', '30', '-i', still]
        timing = 'fps=30'
    else:
        unique = OUT / 'clips' / f'{name}-{start}-{end}-unique.mp4'
        if not unique.exists():
            transcode(['-ss', start, '-t', end-start, '-i', SOURCE, '-an', '-vf',
                       'crop=1800:864:60:52,mpdecimate,setpts=N/(30*TB)',
                       '-c:v', 'libx264', '-threads', '6', '-preset', 'veryfast',
                       '-crf', '16', '-fps_mode', 'passthrough', unique])
        source_frames = int(probe(unique)['streams'][0]['nb_frames'])
        ratio = (duration - .1) / max((source_frames-1)/30, .033333)
        inputs = ['-i', unique]
        # Optical flow is used only to fill small time gaps after duplicate removal.
        # A bounded search keeps the full-resolution pass tractable.
        timing = f'settb=AVTB,setpts=PTS*{ratio:.9f}'
        aerial = name in {'02-reveal', '16-wellness-flight', '20-sports-flight', '26-pullback'}
        if aerial and source_frames < frames * .88 and source_frames > 8:
            timing += (',minterpolate=fps=30:mi_mode=mci:mc_mode=obmc:me_mode=bilat:'
                       'me=epzs:mb_size=16:search_param=8:vsbmc=1')
            smoothing = 'duplicate removal + motion compensated retiming'
        elif source_frames < frames * .88:
            timing = f'setpts=N/(30*TB),fps=30,tpad=stop_mode=clone:stop_duration={duration}'
            smoothing = 'clean accelerated move + endpoint hold'
        else:
            timing += ',fps=30'
            smoothing = 'duplicate removal + retiming'
        timing += ',tpad=stop_mode=clone:stop_duration=1'
    graph = (f'[0:v]{timing},scale=1920:922:flags=lanczos,setsar=1,'
             f'pad=1920:1080:0:0:color=0x101416[canvas];'
             '[canvas][1:v]overlay=0:922:shortest=1,format=yuv420p[out]')
    transcode([*inputs, '-loop', '1', '-i', footer, '-filter_complex_threads', '2',
               '-filter_complex', graph, '-map', '[out]', '-an', '-frames:v', frames,
               '-r', '30', '-c:v', 'libx264', '-threads', '6', '-preset', 'fast',
               '-crf', '18', '-video_track_timescale', '30000', path])
    return dict(name=name, sourceIn=start, sourceOut=end, duration=frames/30,
                uniqueSourceFrames=source_frames, processing=smoothing, path=str(path))


def render():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    existing = {}
    manifest = OUT / 'edit-manifest.json'
    if manifest.exists():
        existing = {item['name']: item for item in json.loads(manifest.read_text(encoding='utf-8'))}
    for i, shot in enumerate(SHOTS):
        if (shot[0] in existing and Path(existing[shot[0]]['path']).exists()
                and existing[shot[0]]['sourceIn'] == shot[1]
                and existing[shot[0]]['sourceOut'] == shot[2]
                and existing[shot[0]]['duration'] == shot[3]
                and existing[shot[0]]['processing'] != 'duplicate removal + frame blended retiming'):
            results.append(existing[shot[0]])
            continue
        started = time.time()
        print(f'RENDER {i+1}/{len(SHOTS)} {shot[0]}', flush=True)
        result = render_shot(shot)
        result['renderSeconds'] = round(time.time()-started, 1)
        results.append(result)
        (OUT / 'edit-manifest.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)
    (OUT / 'edit-manifest.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    assemble(results)


def assemble(results=None):
    if results is None:
        results = json.loads((OUT / 'edit-manifest.json').read_text(encoding='utf-8'))
    inputs, filters, chapters = [], [], []
    boundaries = [0, 6, 7, 13, 16, 21, len(results)]
    # Assemble clean cuts losslessly first, limiting concurrent decoders to six.
    for i, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        listing = OUT / f'chapter-{i}.ffconcat'
        listing.write_text('ffconcat version 1.0\n' + ''.join(
            f"file '{Path(item['path']).as_posix()}'\n" for item in results[start:end]), encoding='utf-8')
        chapter = OUT / f'chapter-{i}.mp4'
        transcode(['-f', 'concat', '-safe', '0', '-i', listing, '-c', 'copy', chapter])
        chapters.append(sum(item['duration'] for item in results[start:end]))
        inputs += ['-threads', '1', '-i', chapter]
        filters.append(f'[{i}:v]fps=30,settb=AVTB,setpts=PTS-STARTPTS[v{i}]')
    current = 'v0'
    total = chapters[0]
    for i, duration in enumerate(chapters[1:], 1):
        overlap = 8 / 30
        filters.append(f'[{current}][v{i}]xfade=transition=fade:duration={overlap:.9f}:'
                       f'offset={total-overlap:.9f}[join{i}]')
        current = f'join{i}'
        total += duration - overlap
    filters.append(f'[{current}]fade=t=in:d=0.3,fade=t=out:st={total-.8:.6f}:d=0.8,'
                   'fps=30,format=yuv420p[film]')
    silent = OUT / 'apex-gym-picture-master.mp4'
    print(f'ASSEMBLE {total:.3f} seconds', flush=True)
    transcode([*inputs, '-filter_complex_threads', '2', '-filter_complex', ';'.join(filters),
               '-map', '[film]', '-an', '-c:v', 'libx264', '-threads', '8', '-preset', 'fast',
               '-crf', '17', '-r', '30', '-movflags', '+faststart', silent])
    total = float(probe(silent)['format']['duration'])
    audio_filter = f'atrim=duration={total:.6f},asetpts=PTS-STARTPTS,loudnorm=I=-17:TP=-1.5:LRA=9'
    measured = execute([FFMPEG, '-nostdin', '-v', 'info', '-ss', '24', '-i', MUSIC,
                        '-af', audio_filter + ':print_format=json', '-f', 'null', '-'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE).stderr.decode('utf-8')
    stats = json.JSONDecoder().raw_decode(measured[measured.rfind('{'):])[0]
    normalizer = ('loudnorm=I=-17:TP=-1.5:LRA=9:'
                  f'measured_I={stats["input_i"]}:measured_TP={stats["input_tp"]}:'
                  f'measured_LRA={stats["input_lra"]}:measured_thresh={stats["input_thresh"]}:'
                  f'offset={stats["target_offset"]}:linear=true')
    final = OUT / 'APEX-GYM-InspectorPro-LinkedIn-1080p.mp4'
    transcode(['-i', silent, '-ss', '24', '-i', MUSIC, '-map', '0:v:0', '-map', '1:a:0',
               '-c:v', 'copy', '-af', normalizer + f',afade=t=in:d=0.7,afade=t=out:st={total-2.5:.6f}:d=2.5',
               '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-t', total,
               '-movflags', '+faststart', '-metadata', 'title=APEX GYM | Built in InspectorPro',
               '-metadata', 'comment=Edited from actual InspectorPro screen-recorded footage.', final])
    report = dict(output=str(final), duration=total, width=1920, height=1080, fps=30,
                  narration=False, music=str(MUSIC), musicIn=24, normalization=stats,
                  source=str(SOURCE), sourceUnchanged=True)
    (OUT / 'delivery.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('COMPLETE ' + json.dumps(report), flush=True)


def review():
    sheet = Image.new('RGB', (1920, 7*290), '#101416')
    draw = ImageDraw.Draw(sheet)
    for i, shot in enumerate(SHOTS):
        name, start, end, *_ = shot
        position = start if end is None else (start + end) / 2
        data = execute([FFMPEG, '-v', 'error', '-ss', position, '-i', SOURCE,
                        '-frames:v', '1', '-vf', 'crop=1800:864:60:52,scale=480:230',
                        '-f', 'image2pipe', '-vcodec', 'png', '-'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        x, y = (i % 4) * 480, (i // 4) * 290
        sheet.paste(Image.open(io.BytesIO(data)), (x, y))
        draw.text((x+12, y+240), f'{name} | {position:.1f}s', font=font(19), fill='white')
    sheet.save(OUT / 'selected-shots-review.jpg', quality=94)
    print('SOURCE REVIEW READY', flush=True)


def verify():
    delivery = json.loads((OUT / 'delivery.json').read_text(encoding='utf-8'))
    final = Path(delivery['output'])
    metadata = probe(final)
    video = next(s for s in metadata['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in metadata['streams'] if s['codec_type'] == 'audio')
    assert (video['width'], video['height']) == (1920, 1080)
    assert video['avg_frame_rate'] == '30/1'
    assert video['pix_fmt'] == 'yuv420p'
    assert audio['codec_name'] == 'aac' and audio['channels'] == 2
    assert 90 <= float(metadata['format']['duration']) <= 120
    assert abs(float(video['duration']) - float(audio['duration'])) < .1
    execute([FFMPEG, '-v', 'error', '-i', final, '-f', 'null', '-'],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    measured = execute([FFMPEG, '-nostdin', '-v', 'info', '-i', final, '-vn',
                        '-af', 'loudnorm=I=-17:TP=-1.5:LRA=9:print_format=json',
                        '-f', 'null', '-'], stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE).stderr.decode('utf-8')
    loudness = json.JSONDecoder().raw_decode(measured[measured.rfind('{'):])[0]
    assert float(loudness['input_tp']) < 0, 'Audio clipping detected'
    motion = []
    manifest = json.loads((OUT / 'edit-manifest.json').read_text(encoding='utf-8'))
    assert len(manifest) == len(SHOTS), 'Incomplete saved edit manifest'
    for item in manifest:
        info = probe(item['path'])['streams'][0]
        assert int(info['nb_frames']) == round(item['duration'] * 30), item['name']
        if item['sourceOut'] is None:
            continue
        data = execute([FFMPEG, '-v', 'error', '-i', item['path'], '-an', '-vf',
                        'crop=1500:620:210:260,scale=160:64,format=gray', '-f', 'rawvideo', '-'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        frames = np.frombuffer(data, np.uint8).reshape((-1, 160*64)).astype(np.int16)
        changes = np.abs(np.diff(frames, axis=0)).mean(axis=1)
        motion.append(dict(name=item['name'], changedFramePercent=round(float((changes>.1).mean()*100), 1)))
    sheet = Image.new('RGB', (1920, 5*294), '#101416')
    draw = ImageDraw.Draw(sheet)
    for i, position in enumerate(np.linspace(1, delivery['duration']-1.3, 20)):
        data = execute([FFMPEG, '-v', 'error', '-ss', position, '-i', final, '-frames:v', '1',
                        '-vf', 'scale=480:270', '-f', 'image2pipe', '-vcodec', 'png', '-'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        x, y = (i % 4) * 480, (i // 4) * 294
        sheet.paste(Image.open(io.BytesIO(data)), (x, y))
        draw.text((x+10, y+271), f'{position:.1f}s', font=font(16), fill='white')
    sheet.save(OUT / 'final-review.jpg', quality=95)
    transcode(['-ss', delivery['duration']-2, '-i', final, '-frames:v', '1',
               '-q:v', '2', OUT / 'APEX-GYM-cover.jpg'])
    report = dict(fullDecode='passed', metadata=metadata, loudness=loudness,
                  motion=motion, bytes=final.stat().st_size)
    (OUT / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(fullDecode='passed', duration=delivery['duration'],
                         megabytes=round(final.stat().st_size/1e6, 1), loudness=loudness,
                         motion=motion)), flush=True)


def execute(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True,
                          creationflags=subprocess.CREATE_NO_WINDOW,
                          stdin=subprocess.DEVNULL, **kwargs)


def analyze():
    OUT.mkdir(parents=True, exist_ok=True)
    command = [str(FFMPEG), '-v', 'error', '-i', str(SOURCE), '-an', '-vf',
               'crop=1500:560:210:300,scale=160:60,format=gray', '-f', 'rawvideo', '-']
    differences = []
    previous = None
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW) as child:
        while True:
            frame = child.stdout.read(160 * 60)
            if not frame:
                break
            if len(frame) != 160 * 60:
                raise RuntimeError('Incomplete analysis frame')
            current = np.frombuffer(frame, np.uint8).astype(np.int16)
            differences.append(float(np.abs(current - previous).mean()) if previous is not None else 0)
            previous = current
        error = child.stderr.read().decode('utf-8', errors='replace')
        if child.wait() != 0:
            raise RuntimeError(error)
    np.save(OUT / 'source-frame-change.npy', differences)
    bands = []
    for start in range(130, 730, 10):
        values = np.array(differences[start * 30:(start + 10) * 30])
        bands.append(dict(start=start, activeFps=round(float((values > .2).sum() / 10), 2),
                          meanChange=round(float(values.mean()), 3)))
    audio = execute([FFMPEG, '-v', 'error', '-i', MUSIC, '-ac', '1', '-ar', '22050',
                     '-f', 'f32le', '-'], stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    samples = np.frombuffer(audio, np.float32)
    frequencies, times, spectrum = signal.stft(samples, fs=22050, nperseg=1024, noverlap=768)
    energy = np.abs(spectrum[(frequencies >= 40) & (frequencies <= 250)]).sum(axis=0)
    onset = np.maximum(0, np.diff(energy, prepend=energy[0]))
    correlation = signal.correlate(onset, onset, mode='full', method='fft')[len(onset)-1:]
    step = 256 / 22050
    lags = np.arange(round(.4 / step), round(.85 / step))
    best = int(lags[np.argmax(correlation[lags])])
    peaks, _ = signal.find_peaks(onset, distance=round(.3 / step), prominence=np.quantile(onset, .85))
    report = dict(duration=len(differences) / 30, tenSecondBands=bands,
                  estimatedBpm=60 / (best * step), beatCandidates=times[peaks].tolist())
    (OUT / 'analysis.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(frames=len(differences), estimatedBpm=report['estimatedBpm'], bands=bands)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['analyze', 'render', 'assemble', 'review', 'verify'])
    args = parser.parse_args()
    if args.command == 'analyze':
        analyze()
    elif args.command == 'render':
        render()
    elif args.command == 'review':
        review()
    elif args.command == 'verify':
        verify()
    else:
        assemble()
