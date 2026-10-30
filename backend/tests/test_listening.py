"""Listening com vídeos locais: regras de lacunas/avaliação, catálogo, cache do processamento e sessões."""

import random
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.domain import listening as rules
from app.main import create_app
from app.media import ffmpeg, subtitles, transcriber
from app.media.subtitles import Cue

SRT = """1
00:00:00,200 --> 00:00:01,400
Never gets old, huh?

2
00:00:01,500 --> 00:00:02,600
<i>I don't know what you were thinking.</i>

3
00:00:02,700 --> 00:00:03,500
[MUSIC PLAYING]
"""

PT_SRT = """1
00:00:00,200 --> 00:00:01,400
Nunca perde a graça, né?

2
00:00:01,500 --> 00:00:02,600
Não sei o que você estava pensando.
"""

needs_ffmpeg = pytest.mark.skipif(not ffmpeg.available(), reason="FFmpeg não instalado")


@pytest.fixture(autouse=True)
def no_real_whisper(monkeypatch):
    """Nos testes o Whisper nunca roda de verdade; sem simulação, a sincronização falha e fica o horário original."""
    def unavailable(*a, **k):
        raise transcriber.TranscriptionError("Whisper desligado nos testes")

    monkeypatch.setattr(transcriber, "transcribe", unavailable)


# ---------- regras ----------

def test_parts_keep_contractions_and_skip_sound_descriptions():
    parts = rules.split_parts("I don't know [MUSIC] 10 times, huh?")
    words = [(p.text, p.eligible) for p in parts if p.word_index is not None]
    assert words == [("I", True), ("don't", True), ("know", True), ("MUSIC", False), ("10", False),
                     ("times", True), ("huh", True)]
    assert "".join(p.text for p in parts) == "I don't know [MUSIC] 10 times, huh?"


@pytest.mark.parametrize("expected,typed,ok", [
    ("don't", "Don’t", True),
    ("don't", "dont", False),
    ("was", "were", False),
    ("huh", "huh?", True),
    ("Never", "never.", True),
    ("know", "  ", False),
    ("goin", "goin'", True),
])
def test_word_comparison(expected, typed, ok):
    assert rules.is_correct(expected, typed) is ok


def test_blank_density_by_difficulty():
    text = " ".join(f"word{i}x" for i in range(40))
    for difficulty, (low, high) in rules.DIFFICULTIES.items():
        counts = [len(rules.choose_blanks(text, difficulty, random.Random(s))) for s in range(200)]
        mean = sum(counts) / len(counts) / 40
        assert low - 0.02 <= mean <= high + 0.02, (difficulty, mean)


def test_at_least_one_blank_and_none_for_unsuitable_sentences():
    assert len(rules.choose_blanks("Yes.", "beginner", random.Random(1))) == 1
    assert rules.choose_blanks("[MUSIC] ♪ 1999 ♪", "hard", random.Random(1)) == []


def test_history_increases_chance_without_fixing_selection():
    text = "the quick brown fox jumps over lazy dogs today again"
    picks = [rules.choose_blanks(text, "beginner", random.Random(s), {"jumps": 1.0}) for s in range(300)]
    jumps_index = rules.words(text).index("jumps")
    with_jumps = sum(jumps_index in p for p in picks)
    assert 300 * 0.2 < with_jumps < 300  # prioriza, mas não esconde sempre a mesma


def test_review_focus_words_are_hidden_first():
    blanks = rules.choose_blanks("I was there when they were young", "beginner", random.Random(3), focus_words={"were"})
    assert rules.words("I was there when they were young").index("were") in blanks


def test_subtitle_parsing_and_translation_alignment():
    cues = subtitles.parse(SRT)
    assert [c.text for c in cues][:2] == ["Never gets old, huh?", "I don't know what you were thinking."]
    vtt = subtitles.parse("WEBVTT\n\n00:01.000 --> 00:02.500 align:start\nHello <b>there</b>\nfriend\n")
    assert vtt[0].start == 1.0 and vtt[0].end == 2.5 and vtt[0].text == "Hello there friend"
    aligned = subtitles.align_translation(cues, subtitles.parse(PT_SRT))
    assert aligned[0] == "Nunca perde a graça, né?" and aligned[2] is None


def test_subtitles_are_resynced_by_spoken_words():
    # caso real (YouTube): a legenda entra 1,2 s depois do "Thank you" e o atraso varia por fala
    cues = [Cue(1.201, 2.769, "-Thank you so much for being here."), Cue(2.769, 3.871, "Welcome, welcome, welcome to the show."),
            Cue(3.871, 5.205, "Congrats."), Cue(40.0, 41.0, "Totally different words here")]
    spoken = [("Thank", 0.0, 0.4), ("you", 0.48, 0.7), ("so", 0.76, 0.95), ("much", 1.0, 1.3), ("for", 1.34, 1.5),
              ("being", 1.56, 1.8), ("here.", 1.82, 2.1), ("Welcome,", 2.44, 2.9), ("welcome,", 3.04, 3.3),
              ("welcome", 3.32, 3.45), ("to", 3.48, 3.6), ("the", 3.66, 3.7), ("show.", 3.72, 3.88),
              ("Congrats.", 3.9, 4.2)]
    out = subtitles.align_to_words(cues, spoken)
    assert out[0].start == 0.0 and out[0].text == "-Thank you so much for being here."
    assert abs(out[1].start - 2.34) < 1e-6 and out[0].end <= out[1].start
    assert abs(out[2].start - 3.88) < 1e-6  # não entra no "show." da fala anterior (termina em 3,88)
    assert (out[3].start, out[3].end) == (40.0, 41.0)  # sem palavra pareada: horário original
    # áudio que não corresponde à legenda: nada muda
    assert subtitles.align_to_words(cues, [("bonjour", 0.0, 0.5), ("merci", 0.6, 1.0)]) == cues


def test_english_detection():
    assert rules.looks_english(["I don't know what you were thinking.", "Never gets old, huh?"])
    assert not rules.looks_english(["Não sei o que você estava pensando.", "Nunca perde a graça, né?"])


# ---------- integração (FFmpeg real, Whisper simulado) ----------

def make_video(path, seconds=4, vcodec="libx264", acodec="aac", extra=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    args = [ffmpeg.find_tool("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=160x90:rate=10:d={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += extra or []
    args += ["-c:v", vcodec, "-c:a", acodec, "-shortest", str(path)]
    subprocess.run(args, check=True, capture_output=True)
    return path


@pytest.fixture
def videos(tmp_path):
    return tmp_path / "videos"


@pytest.fixture
def lclient(tmp_path, videos):
    videos.mkdir()
    app = create_app(tmp_path / "test.db", videos_dir=videos, listening_cache_dir=tmp_path / "cache",
                     inline_worker=True)
    with TestClient(app) as c:
        yield c


def scan(client):
    r = client.post("/api/listening/library/scan")
    assert r.status_code == 200, r.text
    return r.json()


def prepare(client, video_id):
    r = client.post(f"/api/listening/videos/{video_id}/prepare")
    assert r.status_code == 200, r.text
    return r.json()


@needs_ffmpeg
def test_catalog_scan_metadata_and_missing_files_keep_history(lclient, videos):
    make_video(videos / "Series" / "episode_01.mp4")
    lib = scan(lclient)
    assert lib["changes"]["added"] == 1
    video = lib["videos"][0]
    assert video["category"] == "Series" and video["title"] == "episode 01"
    assert video["status"] == "unprocessed" and video["has_thumbnail"] and 3.5 < video["duration"] < 4.5
    assert lclient.get(f"/api/listening/videos/{video['id']}/thumbnail").status_code == 200

    lclient.patch(f"/api/listening/videos/{video['id']}", json={"title": "Meu episódio"})
    (videos / "Series" / "episode_01.mp4").rename(videos / "renamed.mp4")
    lib = scan(lclient)
    assert lib["changes"]["moved"] == 1 and len(lib["videos"]) == 1
    assert lib["videos"][0]["title"] == "Meu episódio" and lib["videos"][0]["category"] == ""

    (videos / "renamed.mp4").unlink()
    lib = scan(lclient)
    assert lib["videos"][0]["present"] is False  # sumiu da pasta, mas o registro (e o histórico) fica


@needs_ffmpeg
def test_external_subtitle_is_used_and_ready_video_is_not_reprocessed(lclient, videos, monkeypatch):
    make_video(videos / "ep.mp4")
    (videos / "ep.en.srt").write_text(SRT, encoding="utf-8")
    (videos / "ep.pt-BR.srt").write_text(PT_SRT, encoding="utf-8")
    vid = scan(lclient)["videos"][0]["id"]
    heard = [Cue(0.0, 1.2, "Never gets old huh", [("Never", 0.0, 0.3), ("gets", 0.35, 0.6), ("old", 0.65, 0.9),
                                                    ("huh", 0.95, 1.2)]),
             Cue(1.7, 2.6, "I don't know what you were thinking",
                 [(w, 1.7 + 0.12 * i, 1.8 + 0.12 * i) for i, w in enumerate("I don't know what you were thinking".split())])]
    monkeypatch.setattr(transcriber, "transcribe", lambda *a, **k: heard)  # Whisper só mede o tempo das palavras

    video = prepare(lclient, vid)
    assert video["status"] == "ready" and video["subtitle_source"] == "external" and video["has_translation"]
    assert video["converted"] is False  # MP4 H.264/AAC toca como está
    segs = lclient.get(f"/api/listening/videos/{vid}/segments").json()
    assert segs[1]["text"] == "I don't know what you were thinking."
    assert segs[0]["start"] == 0.0 and segs[0]["text"] == "Never gets old, huh?"  # ressincronizada (era 0,2 s)
    assert abs(segs[1]["start"] - 1.6) < 1e-6
    assert segs[0]["translation_pt"] == "Nunca perde a graça, né?"

    calls = []
    monkeypatch.setattr("app.services.listening_media.prepare", lambda *a, **k: calls.append(a))
    assert prepare(lclient, vid)["status"] == "ready"
    assert calls == []  # reabrir um vídeo pronto não reprocessa


@needs_ffmpeg
def test_embedded_subtitle_and_conversion_only_when_needed(lclient, videos, tmp_path):
    srt = tmp_path / "in.srt"
    srt.write_text(SRT, encoding="utf-8")
    make_video(videos / "movie.mkv", extra=["-i", str(srt), "-map", "0:v", "-map", "1:a", "-map", "2:s",
                                            "-c:s", "srt", "-metadata:s:s:0", "language=eng"])
    vid = scan(lclient)["videos"][0]["id"]
    video = prepare(lclient, vid)
    assert video["status"] == "ready", video
    assert video["subtitle_source"] == "embedded"
    assert video["converted"] is True  # MKV vira MP4 (cópia do vídeo, sem recodificar)
    r = lclient.get(f"/api/listening/videos/{vid}/stream", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and r.headers["content-type"] == "video/mp4"


@needs_ffmpeg
def test_whisper_fallback_and_recoverable_failure(lclient, videos, monkeypatch):
    make_video(videos / "talk.webm", vcodec="libvpx-vp9", acodec="libopus")
    vid = scan(lclient)["videos"][0]["id"]

    def broken(*a, **k):
        raise transcriber.TranscriptionError("GPU indisponível")

    monkeypatch.setattr(transcriber, "transcribe", broken)
    video = prepare(lclient, vid)
    assert video["status"] == "error" and "GPU" in video["error_message"]

    monkeypatch.setattr(transcriber, "transcribe", lambda audio, *a, **k: [Cue(0.1, 1.5, "Hello there, my friend.")])
    video = prepare(lclient, vid)  # "Tentar novamente"
    assert video["status"] == "ready" and video["subtitle_source"] == "whisper" and video["converted"] is False


@needs_ffmpeg
def test_changed_content_invalidates_cache(lclient, videos):
    path = make_video(videos / "ep.mp4")
    (videos / "ep.srt").write_text(SRT, encoding="utf-8")  # sem idioma no nome: confere que é inglês
    vid = scan(lclient)["videos"][0]["id"]
    assert prepare(lclient, vid)["subtitle_source"] == "external"
    make_video(path, seconds=3)
    lib = scan(lclient)
    assert lib["changes"]["changed"] == 1 and lib["videos"][0]["status"] == "unprocessed"


@needs_ffmpeg
def test_session_flow_attempts_help_replays_and_resume(lclient, videos):
    make_video(videos / "ep.mp4")
    (videos / "ep.en.srt").write_text(SRT, encoding="utf-8")
    vid = scan(lclient)["videos"][0]["id"]
    prepare(lclient, vid)

    r = lclient.post(f"/api/listening/videos/{vid}/sessions", json={"difficulty": "hard", "interval": 0})
    assert r.status_code == 201, r.text
    session = r.json()
    assert len(session["items"]) == 2  # "[MUSIC PLAYING]" não vira exercício
    item = session["items"][1]
    assert item["text"] is None and all(p["text"] is None for p in item["parts"] if p["blank"] is not None)

    # a mesma sessão volta ao "recarregar" (lacunas estáveis)
    again = lclient.post(f"/api/listening/videos/{vid}/sessions", json={"difficulty": "hard", "interval": 0}).json()
    assert again["id"] == session["id"] and again["items"][1]["blanks"] == item["blanks"]

    words = rules.words("I don't know what you were thinking.")
    expected = [words[b["word_index"]] for b in item["blanks"]]
    sid, iid = session["id"], item["id"]
    lclient.post(f"/api/listening/sessions/{sid}/items/{iid}/replay")
    lclient.post(f"/api/listening/sessions/{sid}/items/{iid}/replay")

    wrong = ["zzz"] + [None] * (len(expected) - 1)
    out = lclient.post(f"/api/listening/sessions/{sid}/items/{iid}/check", json={"answers": wrong}).json()
    assert out["item"]["blanks"][0]["state"] == "wrong" and out["item"]["status"] == "pending"
    assert out["session"]["stats"]["attempts"] == 1  # lacunas vazias não contam
    out = lclient.post(f"/api/listening/sessions/{sid}/items/{iid}/check", json={"answers": wrong}).json()
    assert out["session"]["stats"]["attempts"] == 1  # reenviar a mesma resposta errada não é outro erro

    out = lclient.post(f"/api/listening/sessions/{sid}/items/{iid}/reveal", json={"blank": 0}).json()
    assert out["item"]["blanks"][0]["state"] == "revealed" and out["item"]["blanks"][0]["answer"] == expected[0]
    answers = [None] + [w.upper() for w in expected[1:]]
    out = lclient.post(f"/api/listening/sessions/{sid}/items/{iid}/check", json={"answers": answers}).json()
    assert out["item"]["status"] == "done" and out["item"]["text"] == "I don't know what you were thinking."
    stats = out["session"]["stats"]
    assert stats["helped"] == 1 and stats["correct"] == len(expected) - 1  # ajuda não conta como acerto

    lclient.put(f"/api/listening/sessions/{sid}/position", json={"index": 1})
    state = lclient.get(f"/api/listening/sessions/{sid}").json()
    assert state["current_index"] == 1 and state["items"][1]["replays"] == 2

    panel = lclient.get("/api/listening/stats").json()
    first = next(w for w in panel["words"] if w["word"] == rules.normalize_word(expected[0]))
    assert first["attempts"] == 2 and first["errors"] == 2  # erro digitado + ajuda
    assert panel["progress"][0]["segments_done"] == 1 and panel["progress"][0]["to_review"] == 1
    assert panel["sessions"][0]["replays"] == 2

    # revisão reaproveita trechos processados e foca nas palavras erradas
    review = lclient.post(f"/api/listening/videos/{vid}/sessions", json={"difficulty": "beginner", "mode": "review"})
    assert review.status_code == 201, review.text
    rv = review.json()
    assert len(rv["items"]) == 1 and words.index(expected[0]) in [b["word_index"] for b in rv["items"][0]["blanks"]]


@needs_ffmpeg
def test_other_difficulty_creates_new_blanks_without_reprocessing(lclient, videos, monkeypatch):
    make_video(videos / "ep.mp4")
    (videos / "ep.en.srt").write_text(SRT, encoding="utf-8")
    vid = scan(lclient)["videos"][0]["id"]
    prepare(lclient, vid)
    monkeypatch.setattr("app.services.listening_media.prepare", lambda *a, **k: pytest.fail("reprocessou"))
    easy = lclient.post(f"/api/listening/videos/{vid}/sessions", json={"difficulty": "beginner", "interval": 0}).json()
    hard = lclient.post(f"/api/listening/videos/{vid}/sessions", json={"difficulty": "hard", "interval": 0}).json()
    assert easy["id"] != hard["id"]
    assert sum(len(i["blanks"]) for i in hard["items"]) > sum(len(i["blanks"]) for i in easy["items"])


@needs_ffmpeg
def test_segment_correction_and_mismatch_flag(lclient, videos):
    make_video(videos / "ep.mp4")
    (videos / "ep.en.srt").write_text(SRT, encoding="utf-8")
    vid = scan(lclient)["videos"][0]["id"]
    prepare(lclient, vid)
    session = lclient.post(f"/api/listening/videos/{vid}/sessions", json={"difficulty": "medium", "interval": 0}).json()
    item = session["items"][0]
    out = lclient.post(f"/api/listening/sessions/{session['id']}/items/{item['id']}/skip",
                       json={"mismatch": True}).json()
    assert out["item"]["status"] == "skipped" and out["item"]["flagged"]

    seg = lclient.get(f"/api/listening/videos/{vid}/segments").json()[0]
    assert seg["flagged"]
    r = lclient.patch(f"/api/listening/segments/{seg['id']}", json={"text": "It never gets old, huh?", "end": 1.3})
    fixed = r.json()
    assert fixed["edited"] and not fixed["flagged"] and fixed["original_text"] == "Never gets old, huh?"
    assert lclient.patch(f"/api/listening/segments/{seg['id']}", json={"end": 0.1}).status_code == 422


# ---------- downloads do YouTube (yt-dlp simulado) ----------

from app.media import youtube  # noqa: E402


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw", "jNQXAC9IVRw"),
    ("https://youtu.be/jNQXAC9IVRw?t=10", "jNQXAC9IVRw"),
    ("https://www.youtube.com/watch?list=PL1&v=jNQXAC9IVRw&index=2", "jNQXAC9IVRw"),
    ("https://m.youtube.com/shorts/jNQXAC9IVRw", "jNQXAC9IVRw"),
    ("https://vimeo.com/123456", None),
    ("https://www.youtube.com/watch?v=short", None),
])
def test_youtube_url_parsing(url, expected):
    assert youtube.video_id(url) == expected


@needs_ffmpeg
def test_download_lands_in_category_folder_and_gets_prepared(lclient, videos, monkeypatch):
    def fake_download(yt_id, work_dir, max_height, on_progress=None):
        work_dir.mkdir(parents=True, exist_ok=True)
        video = make_video(work_dir / f"Me at the zoo [{yt_id}].mp4")
        sub = work_dir / f"Me at the zoo [{yt_id}].en.vtt"
        sub.write_text("WEBVTT\n\n00:00.500 --> 00:02.000\nAll right, so here we are.\n", encoding="utf-8")
        on_progress("Baixando o vídeo", 0.5)
        return {"title": "Me at the zoo", "video": video, "subtitles": [sub]}

    monkeypatch.setattr(youtube, "download", fake_download)
    r = lclient.post("/api/listening/downloads", json={"url": "https://youtu.be/jNQXAC9IVRw", "category": "../YouTube"})
    assert r.status_code == 201, r.text

    lib = lclient.get("/api/listening/library").json()
    download = lib["downloads"][0]
    assert download["status"] == "done" and download["rel_path"] == "YouTube/Me at the zoo [jNQXAC9IVRw].mp4"
    video = lib["videos"][0]
    assert video["title"] == "Me at the zoo" and video["category"] == "YouTube"
    assert video["status"] == "ready" and video["subtitle_source"] == "external"  # legenda .en.vtt do YouTube

    again = lclient.post("/api/listening/downloads", json={"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_downloaded"


def test_download_errors_are_recoverable(lclient, monkeypatch):
    def broken(*a, **k):
        raise youtube.DownloadError("Video unavailable")

    monkeypatch.setattr(youtube, "download", broken)
    assert lclient.post("/api/listening/downloads", json={"url": "https://vimeo.com/123456"}).status_code == 422
    d = lclient.post("/api/listening/downloads", json={"url": "https://youtu.be/jNQXAC9IVRw"}).json()
    d = lclient.get("/api/listening/downloads").json()[0]
    assert d["status"] == "error" and "unavailable" in d["error_message"]
    assert lclient.post(f"/api/listening/downloads/{d['id']}/retry").json()["status"] == "error"
    assert lclient.delete(f"/api/listening/downloads/{d['id']}").status_code == 204
    assert lclient.get("/api/listening/downloads").json() == []


# ---------- ritmo e lacunas fixas ----------

def test_exercise_lines_follow_the_rhythm():
    # 9 minutos com uma fala a cada ~2 s (como o vídeo real: 251 falas)
    segs = [{"id": i, "start": i * 2.1, "end": i * 2.1 + 1.9,
             "text": "Yes." if i % 5 == 0 else f"this is a sentence number {i} with several words"} for i in range(257)]
    picked = rules.select_exercise_lines(segs, 30)
    assert 14 <= len(picked) <= 19
    starts = [segs[i]["start"] for i in picked]
    assert all(b - a >= 15 for a, b in zip(starts, starts[1:]))  # pelo menos meio intervalo de vídeo corrido
    assert all(segs[i]["text"] != "Yes." for i in picked)  # frases curtas demais não viram exercício
    assert rules.select_exercise_lines(segs, 30) == picked  # determinístico
    assert len(rules.select_exercise_lines(segs, 0)) == 257


LONG_SRT = "\n".join(
    f"{i + 1}\n00:00:{i * 4:02},000 --> 00:00:{i * 4 + 3:02},000\nline {i} has some english words to practice\n"
    for i in range(14))


@needs_ffmpeg
def test_rhythm_blanks_are_fixed_and_context_hides_answers(lclient, videos):
    make_video(videos / "long.mp4", seconds=58)
    (videos / "long.en.srt").write_text(LONG_SRT, encoding="utf-8")
    vid = scan(lclient)["videos"][0]["id"]
    prepare(lclient, vid)

    first = lclient.post(f"/api/listening/videos/{vid}/sessions", json={"difficulty": "medium", "interval": 15}).json()
    assert 3 <= len(first["items"]) <= 5 and first["interval_seconds"] == 15
    context = first["context"]
    assert len(context) == 14
    exercise_starts = {i["start"] for i in first["items"]}
    assert all((c["text"] is None) == (c["start"] in exercise_starts) for c in context)  # resposta não vaza

    blanks = {i["segment_id"]: i["blanks"] for i in first["items"]}
    restarted = lclient.post(f"/api/listening/videos/{vid}/sessions",
                             json={"difficulty": "medium", "interval": 15, "restart": True}).json()
    assert restarted["id"] != first["id"]
    assert {i["segment_id"]: i["blanks"] for i in restarted["items"]} == blanks  # mesmas lacunas ao recomeçar

    every_line = lclient.post(f"/api/listening/videos/{vid}/sessions", json={"difficulty": "medium", "interval": 0}).json()
    assert len(every_line["items"]) == 14  # outro ritmo: nova sessão; falas repetidas mantêm as lacunas
    assert all(i["blanks"] == blanks[i["segment_id"]] for i in every_line["items"] if i["segment_id"] in blanks)
    hard = lclient.post(f"/api/listening/videos/{vid}/sessions", json={"difficulty": "hard", "interval": 15}).json()
    assert {i["segment_id"]: i["blanks"] for i in hard["items"]} != blanks  # outra dificuldade, outras lacunas


# ---------- fidelidade ao áudio e nomes ----------

LISA = "Uh, I have to give thanks to my Lilies and my BLINKs out there."


def test_proper_names_and_niche_terms_are_detected():
    texts = [LISA, '"SaWaDiKa" came out... -Oh, I got chills.', "Lilies are my fans.", "I love Thai food in Bangkok.",
             "Thai food is the best.", "On Monday I speak English.", "It's crazy with the numbers."]
    names = rules.proper_names(texts)
    assert {"lilies", "blinks", "sawadika", "bangkok"} <= names
    assert not {"i", "monday", "english", "thai", "it's", "uh", "crazy", "food"} & names  # nacionalidade é vocabulário


def test_alignment_marks_words_the_audio_does_not_have():
    # o que ela realmente fala (Whisper): "I have thanks to my lilies and my blings out there."
    spoken = [(w, 45.8 + 0.3 * i, 46.0 + 0.3 * i)
              for i, w in enumerate("I have thanks to my lilies and my blings out there.".split())]
    out = subtitles.align_to_words([Cue(45.6, 49.6, LISA)], spoken)
    audio = dict(zip(rules.words(LISA), out[0].audio))
    assert audio["Uh"] == "filler" and audio["give"] == "unheard" and audio["thanks"] == "heard"
    assert audio["BLINKs"] == "misheard"  # ouvido como "blings": falado, mas incerto

    allowed = rules.hideable_words(LISA, rules.proper_names([LISA]), out[0].audio)
    # Uh(0) to(3) give(4) Lilies(8) BLINKs(11) ficam de fora; o segundo "to" (thanks to) foi falado
    assert allowed == {1, 2, 5, 6, 7, 9, 10, 12, 13}


@needs_ffmpeg
def test_sessions_never_hide_unheard_words_or_names_and_history_ignores_them(lclient, videos, monkeypatch):
    make_video(videos / "ep.mp4")
    (videos / "ep.en.srt").write_text(
        "1\n00:00:00,500 --> 00:00:03,000\n" + LISA + "\n", encoding="utf-8")
    heard = [Cue(0.5, 3.0, "I have thanks to my lilies and my blings out there.",
                 [(w, 0.5 + 0.2 * i, 0.65 + 0.2 * i)
                  for i, w in enumerate("I have thanks to my lilies and my blings out there.".split())])]
    monkeypatch.setattr(transcriber, "transcribe", lambda *a, **k: heard)
    vid = scan(lclient)["videos"][0]["id"]
    prepare(lclient, vid)

    words = rules.words(LISA)
    forbidden = {words.index(w) for w in ("Uh", "to", "give", "Lilies", "BLINKs")}  # o primeiro "to" não é falado
    session = lclient.post(f"/api/listening/videos/{vid}/sessions", json={"difficulty": "hard", "interval": 0}).json()
    item = session["items"][0]
    assert not {b["word_index"] for b in item["blanks"]} & forbidden
    shown = {p["text"]: p.get("unheard") for p in item["parts"] if p["blank"] is None and p["text"].strip(" ,.")}
    assert shown["give"] is True and shown["Lilies"] is False  # "give" aparece riscada

    # um erro antigo em "Lilies" (de antes desta regra) some do painel e da revisão
    from app.db import connect
    conn = connect(lclient.app.state.db_path)
    seg_id = item["segment_id"]
    conn.execute(
        """INSERT INTO listening_word_attempts (session_id, item_id, video_id, segment_id, word_index, expected,
           expected_norm, typed, is_correct, used_help, replays, segment_start, segment_text, created_at)
           VALUES (?, ?, ?, ?, ?, 'Lilies', 'lilies', 'lily', 0, 0, 0, 0.5, ?, '2026-10-30T00:00:00')""",
        (session["id"], item["id"], vid, seg_id, words.index("Lilies"), LISA))
    conn.commit()
    conn.close()
    panel = lclient.get("/api/listening/stats").json()
    assert "lilies" not in {w["word"] for w in panel["words"]}


def test_overlapping_speech_never_cuts_heard_words_of_the_previous_line():
    # caso real: "-Yeah. -It comes out next month." começa com fala sobreposta que o Whisper não separa;
    # a estimativa do início dela não pode cortar o "Press Play" da fala anterior
    cues = [Cue(114.381, 116.416, 'by the way, you have a new EP, "Press Play."'),
            Cue(116.416, 118.151, "-Yeah. -It comes out next month.")]
    spoken = [("by", 114.28, 114.38), ("the", 114.38, 114.50), ("way.", 114.50, 114.56), ("You", 114.56, 114.70),
              ("have", 114.70, 114.82), ("a", 114.82, 114.90), ("new", 114.90, 115.06), ("EP,", 115.06, 115.32),
              ("Press", 115.50, 115.78), ("Play,", 115.78, 116.12), ("comes", 116.30, 116.74), ("out", 116.74, 116.90),
              ("next", 116.90, 117.08), ("month.", 117.08, 117.48)]
    first, second = subtitles.align_to_words(cues, spoken)
    assert first.end >= 116.12  # o "Play" inteiro toca
    assert second.start >= 116.12 - 0.05 and second.end >= 117.48
