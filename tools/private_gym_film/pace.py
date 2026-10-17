"""Calmer revision of the gym film, preserving the original exports."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import time

import numpy as np
from PIL import Image, ImageDraw

import edit

PREVIOUS = edit.OUT
OUT = PREVIOUS / 'paced-revision'
FINAL = OUT / 'APEX-GYM-InspectorPro-Calmer-Tour-1080p.mp4'
FPS = 30
OVERLAP = 15 / FPS
STYLE = 'paced-v1'
SOURCE_FRAMES = False
BASE = {shot[0]: shot for shot in edit.SHOTS}

# Keep one readable camera action per shot. Split large viewpoint reversals
# instead of compressing them into a continuous, disorienting turn.
SHOTS = [
    ('01-plan', '01-plan', 132.5, None, 3.2, 'still'),
    ('02-reveal', '02-reveal', 144, 170, 5.6, 'reuse'),
    ('03-reception', '03-reception', 171.5, None, 3.5, 'still'),
    ('04-training', '04-training', 174, 198, 4.2, 'reuse'),
    ('05-strength', '05-strength', 275, 288.3, 4.8, 'move'),
    ('06-equipment', '06-equipment', 303.5, None, 3.2, 'still'),
    ('07-warrior-entrance', '07-warriors', 324.6, 330, 4.2, 'move'),
    ('08-warrior-gallery', '07-warriors', 363.3, 369.8, 5.8, 'move'),
    ('09-office', '08-office', 340.3, None, 3.8, 'still'),
    ('10-conference', '09-conference', 355.5, None, 3.8, 'still'),
    ('11-lounge', '10-lounge', 371, 376.4, 4.8, 'move'),
    ('12-games', '11-games', 402, 408, 3.8, 'move'),
    ('13-kitchen-arrival', '12-kitchen', 419.5, 423.5, 4.5, 'move'),
    ('14-kitchen-detail', '12-kitchen', 429.5, None, 3.2, 'still'),
    ('15-cafe', '13-cafe', 438.5, None, 3.0, 'still'),
    ('16-recovery', '14-recovery', 219.6, None, 3.8, 'still'),
    ('17-pool', '15-pool', 495.1, 503.9, 5.4, 'move'),
    ('18-wellness-flight', '16-wellness-flight', 514, 538, 4.2, 'reuse'),
    ('19-boxing', '17-boxing', 540, 549, 3.8, 'move'),
    ('20-bags', '18-bags', 553.8, 556.8, 3.2, 'move'),
    ('21-basketball', '19-basketball', 562.4, 575.3, 5.8, 'move'),
    ('22-sports-flight', '20-sports-flight', 585, 611, 5.6, 'reuse'),
    ('23-soccer-arrival', '21-soccer', 616.5, None, 4.8, 'still'),
    ('24-soccer-field', '21-soccer', 625.5, None, 4.2, 'still'),
    ('25-outdoor', '22-outdoor', 646.4, 657.3, 4.8, 'move'),
    ('26-turf', '23-turf', 659.3, 671.5, 4.8, 'move'),
    ('27-calisthenics', '24-calisthenics', 681.1, 686, 4.2, 'move'),
    ('28-patio', '25-patio', 705.3, None, 3.8, 'still'),
    ('29-pullback', '26-pullback', 706, 723, 5.6, 'reuse'),
    ('30-close', '27-close', 723, None, 3.6, 'still'),
]


def prepare():
    for folder in ('clips', 'panels', 'source', 'reviews', 'joins'):
        (OUT / folder).mkdir(parents=True, exist_ok=True)
    edit.OUT = OUT


def fingerprint(shot):
    return hashlib.sha256(json.dumps([STYLE, shot]).encode()).hexdigest()


def render_shot(shot):
    name, base, start, end, duration, mode = shot
    path = OUT / 'clips' / f'{name}.mp4'
    report_path = path.with_suffix('.json')
    key = fingerprint(shot)
    if path.exists() and report_path.exists():
        report = json.loads(report_path.read_text())
        if report['fingerprint'] == key:
            return report
    frames = round(duration * FPS)
    began = time.time()
    print(f'RENDER {name}: {duration:.1f}s', flush=True)
    count = None
    if mode == 'reuse' and not SOURCE_FRAMES:
        shutil.copyfile(PREVIOUS / 'clips' / f'{base}.mp4', path)
    else:
        footer = edit.panel((name, start, end, duration, *BASE[base][4:]))
        if mode == 'still':
            still = OUT / 'source' / f'{name}.png'
            edit.transcode(['-ss', start, '-i', edit.SOURCE, '-frames:v', '1',
                            '-vf', 'crop=1800:864:60:52', still])
            inputs = ['-loop', '1', '-framerate', FPS, '-i', still]
            timing = 'fps=30'
        else:
            unique = OUT / 'source' / f'{name}-{start}-{end}.mp4'
            if not unique.exists():
                edit.transcode(['-ss', start, '-t', end-start, '-i', edit.SOURCE,
                                '-an', '-vf', 'crop=1800:864:60:52,mpdecimate,setpts=N/(30*TB)',
                                '-c:v', 'libx264', '-threads', '6', '-preset',
                                'ultrafast' if SOURCE_FRAMES else 'veryfast',
                                '-crf', '0' if SOURCE_FRAMES else '16',
                                '-fps_mode', 'passthrough', unique])
            count = int(edit.probe(unique)['streams'][0]['nb_frames'])
            assert count > 3, f'Not enough motion frames: {name}'
            inputs = ['-i', unique]
            moving = duration - 1.1
            # Mild easing spreads movement over its allotted time, with a slower
            # arrival, rather than playing all unique frames at 30fps then freezing.
            fraction = f'N/{count-1}'
            timestamp = f'({fraction}+0.25*sin(2*PI*{fraction})/(2*PI))*{moving}/TB'
            if SOURCE_FRAMES:
                # Repeat recorded frames, never synthesize motion or reduce
                # spatial resolution. Intermediate encodes are lossless.
                if mode == 'reuse':
                    timestamp = f'{fraction}*{duration-.1}/TB'
                    timing = (f'settb=AVTB,setpts={timestamp},fps=30:round=near,'
                              'tpad=stop_mode=clone:stop_duration=2')
                else:
                    timing = (f'settb=AVTB,setpts={timestamp},fps=30:round=near,'
                              'tpad=start_mode=clone:start_duration=0.4:'
                              'stop_mode=clone:stop_duration=2')
            else:
                timing = (f'scale=1280:614:flags=lanczos,settb=AVTB,setpts={timestamp},'
                          'minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bilat:'
                          'me=epzs:mb_size=16:search_param=16:vsbmc=1,'
                          'tpad=start_mode=clone:start_duration=0.4:'
                          'stop_mode=clone:stop_duration=2,fps=30')
        graph = (f'[0:v]{timing},scale=1920:922:flags=lanczos,setsar=1,'
                 'pad=1920:1080:0:0:color=0x101416[canvas];'
                 '[canvas][1:v]overlay=0:922:shortest=1,format=yuv420p[out]')
        edit.transcode([*inputs, '-loop', '1', '-i', footer,
                        '-filter_complex_threads', '2', '-filter_complex', graph,
                        '-map', '[out]', '-an', '-frames:v', frames, '-r', FPS,
                        '-c:v', 'libx264', '-threads', '6', '-preset',
                        'ultrafast' if SOURCE_FRAMES else 'fast',
                        '-crf', '0' if SOURCE_FRAMES else '17',
                        '-video_track_timescale', '30000', path])
    report = dict(name=name, sourceIn=start, sourceOut=end, duration=frames/FPS,
                  mode='move' if SOURCE_FRAMES and mode == 'reuse' else mode,
                  uniqueFrames=count, path=str(path), fingerprint=key,
                  recordedFramesOnly=SOURCE_FRAMES,
                  renderSeconds=round(time.time()-began, 1))
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
    return report


def assemble(reports):
    # Encode bodies and half-second dissolves separately, then concatenate
    # without re-encoding. This bounds the number of concurrent HD decoders.
    chunks = []
    for i, report in enumerate(reports):
        path = Path(report['path'])
        start = OVERLAP if i else 0
        end = report['duration'] - (OVERLAP if i < len(reports)-1 else 0)
        body = OUT / 'joins' / f'{i:02d}-body.mp4'
        filters = f'trim=start={start}:end={end},setpts=PTS-STARTPTS,fps=30'
        if not i:
            filters += ',fade=t=in:d=0.35'
        if i == len(reports)-1:
            filters += f',fade=t=out:st={end-start-.8}:d=0.8'
        edit.transcode(['-i', path, '-vf', filters, '-an', '-frames:v', round((end-start)*FPS),
                        '-c:v', 'libx264', '-threads', '6', '-preset', 'fast',
                        '-crf', '16' if SOURCE_FRAMES else '17',
                        '-video_track_timescale', '30000', body])
        chunks.append(body)
        if i == len(reports)-1:
            continue
        nxt = reports[i+1]
        dissolve = OUT / 'joins' / f'{i:02d}-dissolve.mp4'
        graph = (f'[0:v]trim=start={report["duration"]-OVERLAP}:end={report["duration"]},'
                 'setpts=PTS-STARTPTS,settb=AVTB[a];'
                 f'[1:v]trim=end={OVERLAP},setpts=PTS-STARTPTS,settb=AVTB[b];'
                 f'[a][b]xfade=transition=fade:duration={OVERLAP}:offset=0,format=yuv420p[v]')
        edit.transcode(['-i', path, '-i', nxt['path'], '-filter_complex_threads', '2',
                        '-filter_complex', graph, '-map', '[v]', '-an',
                        '-frames:v', round(OVERLAP*FPS), '-r', FPS,
                        '-c:v', 'libx264', '-threads', '6', '-preset', 'fast',
                        '-crf', '16' if SOURCE_FRAMES else '17',
                        '-video_track_timescale', '30000', dissolve])
        chunks.append(dissolve)
        print(f'JOIN {i+1}/{len(reports)-1}', flush=True)
    listing = OUT / 'picture.ffconcat'
    listing.write_text('ffconcat version 1.0\n' + ''.join(
        f"file '{path.as_posix()}'\n" for path in chunks))
    silent = OUT / 'picture-master.mp4'
    edit.transcode(['-f', 'concat', '-safe', '0', '-i', listing, '-c', 'copy', silent])
    duration = float(edit.probe(silent)['format']['duration'])
    if SOURCE_FRAMES:
        # Preserve the approved audio bit-for-bit; this revision changes picture only.
        approved = PREVIOUS / 'paced-revision/APEX-GYM-InspectorPro-Calmer-Tour-1080p.mp4'
        assert abs(float(edit.probe(approved)['format']['duration'])-duration) < .1
        edit.transcode(['-i', silent, '-i', approved, '-map', '0:v:0', '-map', '1:a:0',
                        '-c', 'copy', '-movflags', '+faststart', '-metadata',
                        'title=APEX GYM | Clear Tour', FINAL])
        delivery = dict(output=str(FINAL), duration=duration, shots=len(reports),
                        overlapSeconds=OVERLAP, targetLUFS=-23, narration=False,
                        recordedFramesOnly=True, losslessIntermediates=True,
                        source=str(edit.SOURCE), audioCopiedFrom=str(approved))
        (OUT / 'delivery.json').write_text(json.dumps(delivery, indent=2))
        print('COMPLETE ' + json.dumps(delivery), flush=True)
        return
    loudnorm = 'loudnorm=I=-23:TP=-7.5:LRA=9'
    measurement = edit.execute([edit.FFMPEG, '-nostdin', '-v', 'info', '-ss', '24',
                                '-i', edit.MUSIC, '-t', duration, '-af',
                                f'atrim=duration={duration},asetpts=PTS-STARTPTS,'
                                + loudnorm + ':print_format=json', '-f', 'null', '-'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE).stderr.decode()
    stats = json.JSONDecoder().raw_decode(measurement[measurement.rfind('{'):])[0]
    normalization = (loudnorm + f':measured_I={stats["input_i"]}:'
                     f'measured_TP={stats["input_tp"]}:measured_LRA={stats["input_lra"]}:'
                     f'measured_thresh={stats["input_thresh"]}:'
                     f'offset={stats["target_offset"]}:linear=true')
    edit.transcode(['-i', silent, '-ss', '24', '-i', edit.MUSIC,
                    '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
                    '-af', normalization + f',afade=t=in:d=0.7,afade=t=out:st={duration-2.5}:d=2.5',
                    '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-t', duration,
                    '-movflags', '+faststart', '-metadata', 'title=APEX GYM | Calmer Tour', FINAL])
    delivery = dict(output=str(FINAL), duration=duration, shots=len(reports),
                    overlapSeconds=OVERLAP, targetLUFS=-23, narration=False,
                    source=str(edit.SOURCE), music=str(edit.MUSIC))
    (OUT / 'delivery.json').write_text(json.dumps(delivery, indent=2))
    print('COMPLETE ' + json.dumps(delivery), flush=True)


def review(paths, name):
    sheet = Image.new('RGB', (1600, len(paths)*230), '#101416')
    draw = ImageDraw.Draw(sheet)
    for row, path in enumerate(paths):
        duration = float(edit.probe(path)['format']['duration'])
        for col, position in enumerate(np.linspace(.7, duration-.7, 4)):
            data = edit.execute([edit.FFMPEG, '-v', 'error', '-ss', position,
                                 '-i', path, '-frames:v', '1', '-vf', 'scale=400:225',
                                 '-f', 'image2pipe', '-vcodec', 'png', '-'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
            sheet.paste(Image.open(io.BytesIO(data)), (col*400, row*230))
            draw.text((col*400+8, row*230+4), f'{path.stem} {position:.1f}s',
                      font=edit.font(15), fill='white', stroke_width=1, stroke_fill='black')
    sheet.save(OUT / 'reviews' / name, quality=95)


def verify():
    metadata = edit.probe(FINAL)
    video = next(x for x in metadata['streams'] if x['codec_type'] == 'video')
    audio = next(x for x in metadata['streams'] if x['codec_type'] == 'audio')
    reports = json.loads((OUT / 'edit-manifest.json').read_text())
    expected = sum(x['duration'] for x in reports) - OVERLAP*(len(reports)-1)
    assert (video['width'], video['height'], video['avg_frame_rate']) == (1920, 1080, '30/1')
    assert abs(float(video['duration'])-expected) < .1
    assert abs(float(video['duration'])-float(audio['duration'])) < .1
    edit.execute([edit.FFMPEG, '-v', 'error', '-i', FINAL, '-f', 'null', '-'],
                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    motion = []
    for shot in reports:
        info = edit.probe(shot['path'])['streams'][0]
        assert int(info['nb_frames']) == round(shot['duration']*FPS), shot['name']
        if shot['mode'] != 'move':
            continue
        data = edit.execute([edit.FFMPEG, '-v', 'error', '-i', shot['path'], '-an',
                             '-vf', 'crop=1500:600:210:270,scale=160:64,format=gray',
                             '-f', 'rawvideo', '-'], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE).stdout
        frames = np.frombuffer(data, np.uint8).reshape((-1, 160*64)).astype(np.int16)
        changes = np.abs(np.diff(frames, axis=0)).mean(axis=1)
        moving = np.flatnonzero(changes > .1)
        span = (int(moving[-1])-int(moving[0])+1)/FPS if len(moving) else 0
        motion.append(dict(name=shot['name'], motionSpan=round(span, 2),
                           maxFrameChange=round(float(changes.max()), 2)))
    measured = edit.execute([edit.FFMPEG, '-v', 'info', '-i', FINAL, '-vn', '-af',
                             'loudnorm=I=-23:TP=-7.5:LRA=9:print_format=json',
                             '-f', 'null', '-'], stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE).stderr.decode()
    loudness = json.JSONDecoder().raw_decode(measured[measured.rfind('{'):])[0]
    assert -24 < float(loudness['input_i']) < -22
    assert float(loudness['input_tp']) < -5
    review([Path(x['path']) for x in reports], 'all-shots.jpg')
    result = dict(fullDecode='passed', duration=expected, motion=motion,
                  loudness=loudness, megabytes=round(FINAL.stat().st_size/1e6, 1))
    if SOURCE_FRAMES:
        result['frameIntegrity'] = verify_recorded_frames(reports)
        approved = PREVIOUS / 'paced-revision/APEX-GYM-InspectorPro-Calmer-Tour-1080p.mp4'
        audio_hashes = []
        for path in (approved, FINAL):
            data = edit.execute([edit.FFMPEG, '-v', 'error', '-i', path, '-map', '0:a:0',
                                 '-c', 'copy', '-f', 'streamhash', '-hash', 'sha256', '-'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
            audio_hashes.append(data)
        assert audio_hashes[0] == audio_hashes[1], 'Audio differs from the approved quieter mix'
        result['audioUnchanged'] = True
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


def frame_hashes(path, filters):
    data = edit.execute([edit.FFMPEG, '-v', 'error', '-i', path, '-an', '-vf', filters,
                         '-f', 'framemd5', '-'], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE).stdout.decode()
    return [line.rsplit(',', 1)[-1].strip() for line in data.splitlines()
            if line and not line.startswith('#')]


def verify_recorded_frames(reports):
    results = []
    for report in reports:
        if report['mode'] != 'move':
            continue
        unique = OUT / 'source' / f'{report["name"]}-{report["sourceIn"]}-{report["sourceOut"]}.mp4'
        reference = set(frame_hashes(unique, 'scale=1920:922:flags=lanczos,format=yuv420p'))
        actual = frame_hashes(report['path'], 'crop=1920:922:0:0,format=yuv420p')
        unmatched = sum(value not in reference for value in actual)
        assert unmatched == 0, f'{report["name"]}: {unmatched} synthetic or altered picture frames'
        results.append(dict(name=report['name'], frames=len(actual), unmatched=unmatched))
        print(f'ORIGINAL FRAME CHECK {report["name"]}: {len(actual)} exact matches', flush=True)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['render', 'sample', 'assemble', 'verify'])
    parser.add_argument('--source-frames', action='store_true',
                        help='Native-resolution recorded frames only, lossless intermediates')
    args = parser.parse_args()
    if args.source_frames:
        SOURCE_FRAMES = True
        STYLE = 'paced-native-v1'
        OUT = PREVIOUS / 'source-frames-revision'
        FINAL = OUT / 'APEX-GYM-InspectorPro-Clear-Tour-1080p.mp4'
    prepare()
    if args.command in {'render', 'sample'}:
        selected = SHOTS if args.command == 'render' else [SHOTS[i] for i in (7, 12, 20, 22, 23)]
        results = [render_shot(shot) for shot in selected]
        if args.command == 'sample':
            review([Path(x['path']) for x in results], 'key-areas.jpg')
            if SOURCE_FRAMES:
                verify_recorded_frames(results)
        else:
            (OUT / 'edit-manifest.json').write_text(json.dumps(results, indent=2))
            assemble(results)
            verify()
    elif args.command == 'assemble':
        assemble(json.loads((OUT / 'edit-manifest.json').read_text()))
    else:
        verify()
