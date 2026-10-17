"""Append the approved APEX outro with no additional picture compression."""
import hashlib
import json
from pathlib import Path
import subprocess

from edit import FFMPEG, MUSIC, OUT, execute, probe, transcode


FILM = OUT / 'source-frames-revision/APEX-GYM-InspectorPro-Clear-Tour-1080p.mp4'
OUTRO = OUT / 'apex-outro-preview/branded-credit/APEX-GYM-Built-in-InspectorPro-Outro-Preview.mp4'
DEST = OUT / 'final-with-outro'
FINAL = DEST / 'APEX-GYM-InspectorPro-Final-1080p.mp4'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def video_info(path):
    return next(s for s in probe(path)['streams'] if s['codec_type'] == 'video')


def measured_audio(path, *, start=None, duration=None):
    args = [FFMPEG, '-nostdin', '-v', 'info']
    if start is not None:
        args += ['-ss', str(start)]
    args += ['-i', path, '-vn']
    if duration is not None:
        args += ['-t', str(duration)]
    prefix = f'atrim=duration={duration},asetpts=PTS-STARTPTS,' if duration is not None else ''
    args += ['-af', prefix + 'loudnorm=I=-23:TP=-7.5:LRA=9:print_format=json', '-f', 'null', '-']
    result = execute(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE).stderr.decode()
    return json.JSONDecoder().raw_decode(result[result.rfind('{'):])[0]


def frame_hashes(path):
    result = execute([FFMPEG, '-v', 'error', '-i', path, '-map', '0:v:0',
                      '-pix_fmt', 'yuv420p', '-f', 'framemd5', '-'],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()
    return [line.rsplit(',', 1)[-1].strip() for line in result.splitlines()
            if line and not line.startswith('#')]


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    protected = {str(path): digest(path) for path in (FILM, OUTRO, MUSIC)}
    film_info, outro_info = video_info(FILM), video_info(OUTRO)
    for info in (film_info, outro_info):
        assert (info['width'], info['height'], info['avg_frame_rate']) == (1920, 1080, '30/1')
    main_duration = float(film_info['duration'])
    duration = main_duration + float(outro_info['duration'])
    print('Copying approved video streams without re-encoding', flush=True)
    segments = []
    for source, name in ((FILM, 'tour'), (OUTRO, 'outro')):
        segment = DEST / f'{name}-picture.mp4'
        transcode(['-i', source, '-map', '0:v:0', '-an', '-c:v', 'copy',
                   '-video_track_timescale', '30000', segment])
        segments.append(segment)
    listing = DEST / 'picture.ffconcat'
    listing.write_text('ffconcat version 1.0\n' + ''.join(
        f"file '{path.as_posix()}'\n" for path in segments), encoding='utf-8')
    picture = DEST / 'picture-master.mp4'
    transcode(['-f', 'concat', '-safe', '0', '-i', listing, '-map', '0:v:0',
               '-c:v', 'copy', '-video_track_timescale', '30000', picture])

    print('Extending the approved quiet music mix through the outro', flush=True)
    # Reuse the original normalization measurement, changing only the end fade.
    stats = measured_audio(MUSIC, start=24, duration=main_duration)
    normalizer = ('loudnorm=I=-23:TP=-7.5:LRA=9:'
                  f'measured_I={stats["input_i"]}:measured_TP={stats["input_tp"]}:'
                  f'measured_LRA={stats["input_lra"]}:measured_thresh={stats["input_thresh"]}:'
                  f'offset={stats["target_offset"]}:linear=true')
    transcode(['-i', picture, '-ss', '24', '-i', MUSIC,
               '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
               '-af', normalizer + f',afade=t=in:d=0.7,afade=t=out:st={duration-2.5}:d=2.5',
               '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-t', duration,
               '-movflags', '+faststart', '-metadata', 'title=APEX GYM | Built in InspectorPro',
               '-metadata', 'comment=Actual InspectorPro walkthrough with approved APEX closing title.', FINAL])

    print('Checking all picture frames against both approved videos', flush=True)
    expected = frame_hashes(FILM) + frame_hashes(OUTRO)
    actual = frame_hashes(FINAL)
    assert expected == actual, 'A picture frame changed during concatenation'
    info = probe(FINAL)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
    assert int(video['nb_frames']) == len(expected) == round(duration * 30)
    assert abs(float(video['duration']) - duration) < .02
    assert abs(float(audio['duration']) - duration) < .05
    execute([FFMPEG, '-v', 'error', '-i', FINAL, '-f', 'null', '-'],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    loudness = measured_audio(FINAL)
    assert -24 < float(loudness['input_i']) < -22
    assert float(loudness['input_tp']) < -5
    old_level = measured_audio(FILM, duration=110)
    new_level = measured_audio(FINAL, duration=110)
    assert abs(float(old_level['input_i']) - float(new_level['input_i'])) < .15
    assert all(digest(Path(path)) == sha for path, sha in protected.items())
    transcode(['-ss', str(main_duration - 1.5), '-i', FINAL, '-t', '6.5',
               '-vf', 'fps=2,scale=480:270,tile=5x3', '-frames:v', '1', DEST / 'ending-review.jpg'])
    transcode(['-ss', str(main_duration + 2.5), '-i', FINAL, '-frames:v', '1', DEST / 'outro-preview.png'])
    report = dict(output=str(FINAL), duration=duration, width=1920, height=1080, fps=30,
                  outroStart=main_duration, exactPictureFrames=len(actual), pictureReencoded=False,
                  decodePassed=True, protectedSourceHashes=protected, sourceFilesUnchanged=True,
                  loudness=loudness, originalFirst110sLUFS=old_level['input_i'],
                  finalFirst110sLUFS=new_level['input_i'], audioFadeOutStart=duration-2.5,
                  megabytes=round(FINAL.stat().st_size / 1e6, 1))
    (DEST / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('COMPLETE ' + json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
