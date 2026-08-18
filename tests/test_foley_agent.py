"""Unit tests for the FoleyAgent (LLM-in-the-loop SFX resolver)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from llm_from_here.plugins.foleyAgent import (
    FoleyAgent,
    FoleyCache,
    FoleyCandidate,
    FoleyProviderError,
    FreesoundProvider,
    normalize_cue,
)
from llm_from_here.plugins.improvAgent import (
    ImprovAgent,
    _DEFAULT_SFX_MAP,
    _MAX_SFX_CUES_PER_TURN,
)
from llm_from_here.plugins.segmentsToTimeline import SegmentsToTimeline
from llm_from_here.schemas.improv_outputs import ImprovTurn, SceneSetup


class _FakeProvider:
    name = "fake"

    def __init__(self, *candidates: FoleyCandidate, fail: bool = False):
        self._candidates = list(candidates)
        self.fail = fail
        self.queries: list[str] = []

    def search(self, query, duration_min_sec, duration_max_sec, num_results=5):
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("provider exploded")
        return list(self._candidates)

    def download(self, candidate, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        p = dest_dir / f"{candidate.candidate_id}.mp3"
        p.write_bytes(b"fake-audio")
        return p


class _FakeSession:
    def __init__(self, steps: list[dict]):
        self.steps = list(steps)
        self.calls = 0

    def run_structured(self, prompt, output_type, **_kw):
        raw = self.steps[self.calls] if self.calls < len(self.steps) else {"give_up": True}
        self.calls += 1
        return raw


def _cand(id_: str, name: str, dur: float | None = 2.0) -> FoleyCandidate:
    return FoleyCandidate(
        provider="fake", candidate_id=id_, name=name, duration_sec=dur
    )


class TestNormalizeCue(unittest.TestCase):
    def test_strips_punctuation_and_collapses_space(self):
        self.assertEqual(normalize_cue("  Coffee machine steam.  "), "Coffee machine steam")
        self.assertEqual(normalize_cue("door  creak!"), "door creak")


class TestFoleyCache(unittest.TestCase):
    def test_put_get_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = FoleyCache(Path(tmp))
            src = Path(tmp) / "src.wav"
            src.write_bytes(b"audio")
            cand = _cand("42", "Door Creaking", 5.0)
            cache.put("door creak", "fake", cand, src)
            entry = cache.get("door creak")
            self.assertEqual(entry["source_id"], "42")
            self.assertEqual(entry["source_name"], "Door Creaking")
            self.assertTrue(Path(entry["path"]).exists())

    def test_get_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = FoleyCache(Path(tmp))
            self.assertIsNone(cache.get("does not exist"))

    def test_get_evicts_when_file_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = FoleyCache(Path(tmp))
            src = Path(tmp) / "src.wav"
            src.write_bytes(b"audio")
            cache.put("ding", "fake", _cand("1", "Bell"), src)
            entry = cache.get("ding")
            assert entry is not None
            Path(entry["path"]).unlink()
            self.assertIsNone(cache.get("ding"))

    def test_cache_index_from_old_version_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "old_file.mp3").write_bytes(b"audio")
            old_key = hashlib.sha256(b"door creak").hexdigest()[:16]
            (root / "index.json").write_text(
                json.dumps({old_key: {"file": "old_file.mp3"}})
            )
            cache = FoleyCache(root)
            # Bumped _CACHE_VERSION must invalidate picks made by older judge logic.
            self.assertIsNone(cache.get("door creak"))


class TestFoleyAgentLoop(unittest.TestCase):
    def _agent(self, tmp: str, providers, steps, **kw) -> FoleyAgent:
        agent = FoleyAgent(cache_dir=tmp, providers=list(providers), **kw)
        agent._session = _FakeSession(steps)
        return agent

    def test_immediate_accept_downloads_and_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = _FakeProvider(_cand("7", "Squeaky Door", 1.9))
            agent = self._agent(tmp, [prov], [{"accept": True, "candidate_ref": "fake:7"}])
            out = Path(tmp) / "out"
            res = agent.resolve("door creak", download_dir=out)
            self.assertEqual(res["status"], "hit")
            self.assertEqual(res["selected"]["id"], "7")
            self.assertTrue(Path(res["file"]).is_file())
            self.assertEqual(prov.queries, ["door creak"])
            # Second resolve for the same intent must reuse the cache, not search.
            agent2 = self._agent(tmp, [], [])
            res2 = agent2.resolve("door creak.", download_dir=out)
            self.assertEqual(res2["status"], "cached")
            self.assertEqual(res2["selected"]["id"], "7")
            self.assertTrue(res2.get("file"))
            self.assertTrue(Path(res2["file"]).is_file())

    def test_refine_then_accept_uses_two_searches(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = _FakeProvider(_cand("3", "Coffee Machine", 3.0))
            agent = self._agent(
                tmp,
                [prov],
                [
                    {"refined_query": "espresso machine hiss"},
                    {"accept": True, "candidate_ref": "fake:3"},
                ],
            )
            res = agent.resolve("cafe coffee pump")
            self.assertEqual(res["status"], "hit")
            self.assertEqual(prov.queries, ["cafe coffee pump", "espresso machine hiss"])

    def test_repeated_refined_query_recovers_with_best_effort_accept(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = _FakeProvider(_cand("1", "One", 1.0))
            agent = self._agent(
                tmp,
                [prov],
                [
                    {"refined_query": "same thing again"},
                    {"refined_query": "same thing again"},
                    {"accept": True, "candidate_ref": "fake:1"},
                ],
            )
            res = agent.resolve("mystery")
            self.assertEqual(res["status"], "hit")
            self.assertEqual(res["selected"]["id"], "1")

    def test_give_up_returns_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = _FakeProvider(_cand("1", "One", 1.0))
            agent = self._agent(tmp, [prov], [{"give_up": True, "give_up_reason": "hopeless"}])
            res = agent.resolve("tense orchestral sting")
            self.assertEqual(res["status"], "miss")
            self.assertEqual(res["reason"], "hopeless")
            self.assertIsNone(res["file"])

    def test_empty_results_and_no_refine_gives_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = _FakeProvider()
            agent = self._agent(tmp, [prov], [{"give_up": True}])
            res = agent.resolve("nonsense")
            self.assertEqual(res["status"], "miss")

    def test_bogus_accepted_ref_recovers_with_best_effort_accept(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = _FakeProvider(_cand("1", "One", 1.0))
            agent = self._agent(tmp, [prov], [{"accept": True, "candidate_ref": "fake:999"}])
            res = agent.resolve("thing")
            self.assertEqual(res["status"], "hit")
            self.assertEqual(res["selected"]["id"], "1")

    def test_attempt_exhaustion_best_effort_accepts_top_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = _FakeProvider(_cand("2", "Top Rated", 2.0))
            agent = self._agent(
                tmp,
                [prov],
                [
                    {"refined_query": "q2"},
                    {"refined_query": "q3"},
                    {"refined_query": "q4"},
                ],
            )
            res = agent.resolve("mystery")
            self.assertEqual(res["status"], "hit")
            self.assertEqual(res["selected"]["id"], "2")
            self.assertEqual(agent.resolve("mystery")["status"], "cached")

    def test_provider_error_then_valid_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = _FakeProvider(_cand("2", "Cup Clink", 1.2))
            bad = _FakeProvider(fail=True)
            agent = self._agent(tmp, [bad, good], [{"accept": True, "candidate_ref": "fake:2"}])
            res = agent.resolve("cup clink")
            self.assertEqual(res["status"], "hit")
            self.assertEqual(res["selected"]["id"], "2")

    def test_free_mode_skips_llm_and_accepts_top_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = _FakeProvider(_cand("5", "Fireplace", 4.0))
            agent = FoleyAgent(cache_dir=tmp, providers=[prov], free_mode=True)
            self.assertIsNone(agent._session)
            res = agent.resolve("fire crackle")
            self.assertEqual(res["status"], "hit")
            self.assertEqual(res["selected"]["id"], "5")
            self.assertIsNone(agent._session)  # no LLM session was ever built


class TestFreesoundProviderUnits(unittest.TestCase):
    def test_search_raises_without_api_key(self):
        prov = FreesoundProvider(api_key="")
        with self.assertRaises(Exception):
            prov.search("door creak", 1, 60)

    def test_search_retries_then_raises(self):
        import requests

        prov = FreesoundProvider(api_key="k")
        with patch("llm_from_here.plugins.foleyAgent.requests.get") as get:
            get.side_effect = [
                requests.exceptions.ConnectTimeout("down"),
                requests.exceptions.ConnectTimeout("down"),
            ]
            with self.assertRaises(FoleyProviderError):
                prov.search("q", 1, 60)
            self.assertEqual(get.call_count, 2)

    def test_search_parses_results(self):
        prov = FreesoundProvider(api_key="k")
        payload = {
            "count": 2,
            "results": [
                {
                    "id": 11,
                    "name": "Door Creak",
                    "duration": 1.5,
                    "previews": {"preview-hq-mp3": "http://x/a.mp3"},
                    "author": {"username": "alice"},
                    "url": "http://x/s/11",
                }
            ],
        }
        with patch("llm_from_here.plugins.foleyAgent.requests.get") as get:
            get.return_value = _FakeResponse(payload)
            cands = prov.search("door creak", 1, 60)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].ref, "freesound:11")
        self.assertEqual(cands[0].name, "Door Creak")
        self.assertEqual(cands[0].author, "alice")

    def test_search_trims_long_phrase_to_noun_query(self):
        prov = FreesoundProvider(api_key="k")
        hit = {
            "count": 1,
            "results": [
                {
                    "id": 5,
                    "name": "Box thud",
                    "duration": 1.2,
                    "previews": {"preview-hq-mp3": "http://x/b.mp3"},
                    "author": {"username": "bob"},
                    "url": "http://x/5",
                }
            ],
        }
        empty = {"count": 0, "results": []}
        queries: list[str] = []

        def fake_get(url, params, headers, timeout):
            queries.append(params["query"])
            payload = hit if params["query"] == "cardboard box" else empty
            return _FakeResponse(payload)

        with patch("llm_from_here.plugins.foleyAgent.requests.get", side_effect=fake_get):
            cands = prov.search("cardboard box place down thud", 1, 60)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].name, "Box thud")
        self.assertEqual(queries[-1], "cardboard box")
        self.assertTrue("cardboard box" in queries)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestSegmentsToTimelineFoley(unittest.TestCase):
    def _stt(self, tmp: str) -> SegmentsToTimeline:
        params = {
            "segments_object": "segs",
            "segment_type_key": "speaker",
            "segment_value_key": "dialog",
            "segment_type_map": {},
        }
        with patch("llm_from_here.plugins.freesoundfetch.FreeSoundFetch"):
            return SegmentsToTimeline(params, {"output_folder": tmp}, "test")

    def test_foley_hit_copies_file_to_output(self):
        import llm_from_here.plugins.foleyAgent as foley_mod

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            foley_mod.FoleyAgent, "resolve", return_value={
                "status": "hit",
                "file": os.path.join(tmp, "dl.mp3"),
                "reason": None,
                "selected": {"provider": "freesound", "id": 1, "name": "Door"},
                "audit": {"attempts": []},
            },
        ):
            src = os.path.join(tmp, "dl.mp3")
            with open(src, "wb") as f:
                f.write(b"mp3-data")
            stt = self._stt(tmp)
            out = os.path.join(tmp, "seg.wav")
            ok = stt.music_generator_foley_agent("[SFX: door creak]", out, cache_dir=tmp)
            self.assertTrue(ok)
            self.assertEqual(open(out, "rb").read(), b"mp3-data")
            self.assertTrue(os.path.isfile(os.path.join(tmp, "foley_audit.json")))

    def test_foley_miss_writes_silence_pad(self):
        import llm_from_here.plugins.foleyAgent as foley_mod

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            foley_mod.FoleyAgent, "resolve", return_value={
                "status": "miss",
                "file": None,
                "reason": "hopeless",
                "selected": None,
                "audit": {"attempts": []},
            },
        ):
            stt = self._stt(tmp)
            out = os.path.join(tmp, "seg.wav")
            ok = stt.music_generator_foley_agent("cruel unicorn neigh", out, cache_dir=tmp)
            self.assertTrue(ok)
            self.assertTrue(os.path.isfile(out))

    def test_foley_cached_copies_file_not_silence(self):
        import llm_from_here.plugins.foleyAgent as foley_mod

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            foley_mod.FoleyAgent, "resolve", return_value={
                "status": "cached",
                "file": os.path.join(tmp, "cached.mp3"),
                "reason": None,
                "selected": {"provider": "freesound", "id": 7, "name": "Bell"},
                "audit": {"attempts": []},
            },
        ):
            cached = os.path.join(tmp, "cached.mp3")
            with open(cached, "wb") as f:
                f.write(b"cache-audio")
            stt = self._stt(tmp)
            out = os.path.join(tmp, "seg.wav")
            ok = stt.music_generator_foley_agent("ding", out, cache_dir=tmp)
            self.assertTrue(ok)
            self.assertEqual(open(out, "rb").read(), b"cache-audio")

    def test_foley_truncates_long_clips_to_cap(self):
        from pydub import AudioSegment

        import llm_from_here.plugins.foleyAgent as foley_mod

        with tempfile.TemporaryDirectory() as tmp:
            long_wav = os.path.join(tmp, "long.wav")
            AudioSegment.silent(duration=5000).export(long_wav, format="wav")
            with patch.object(
                foley_mod.FoleyAgent, "resolve", return_value={
                    "status": "hit",
                    "file": long_wav,
                    "reason": None,
                    "selected": {"provider": "freesound", "id": 1, "name": "Box"},
                    "audit": {"attempts": []},
                },
            ):
                stt = self._stt(tmp)
                out = os.path.join(tmp, "seg.wav")
                ok = stt.music_generator_foley_agent(
                    "[SFX: cardboard box drop]", out, foley_max_duration_sec=1
                )
                self.assertTrue(ok)
                seg = AudioSegment.from_wav(out)
                self.assertLessEqual(len(seg) / 1000.0, 1.2)

    def test_ambience_hit_copies_with_ambience_cache_subdir(self):
        import llm_from_here.plugins.foleyAgent as foley_mod

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            foley_mod.FoleyAgent, "resolve", return_value={
                "status": "hit",
                "file": os.path.join(tmp, "bed.mp3"),
                "reason": None,
                "selected": {"provider": "freesound", "id": 3, "name": "Room Tone"},
                "audit": {"attempts": []},
            },
        ):
            src = os.path.join(tmp, "bed.mp3")
            with open(src, "wb") as f:
                f.write(b"bed-audio")
            stt = self._stt(tmp)
            out = os.path.join(tmp, "bg.wav")
            ok = stt.music_generator_foley_ambience(
                "[BACKGROUND: quiet library hum]", out, cache_dir=tmp
            )
            self.assertTrue(ok)
            self.assertEqual(open(out, "rb").read(), b"bed-audio")
            self.assertTrue(os.path.isdir(os.path.join(tmp, "ambience")))

    def test_ambience_miss_without_fallback_returns_none(self):
        import llm_from_here.plugins.foleyAgent as foley_mod

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            foley_mod.FoleyAgent, "resolve", return_value={
                "status": "miss",
                "file": None,
                "reason": "no matches",
                "selected": None,
                "audit": {"attempts": []},
            },
        ):
            stt = self._stt(tmp)
            out = os.path.join(tmp, "bg.wav")
            res = stt.music_generator_foley_ambience(
                "[BACKGROUND: inscrutable din]",
                out,
                cache_dir=tmp,
                ambience_fallback=False,
            )
            self.assertIsNone(res)
            self.assertFalse(os.path.exists(out))

    def test_ambience_forwards_sustained_to_resolve(self):
        import llm_from_here.plugins.foleyAgent as foley_mod

        with tempfile.TemporaryDirectory() as tmp:
            kwargs: dict = {}
            def fake_resolve(cls, intent, **kw):
                kwargs.update(kw)
                return {"status": "miss", "file": None, "selected": None,
                        "audit": {"attempts": []}}
            with patch.object(foley_mod.FoleyAgent, "resolve", fake_resolve):
                stt = self._stt(tmp)
                stt.music_generator_foley_ambience(
                    "[BACKGROUND: ocean drift]", os.path.join(tmp, "bg.wav"),
                    cache_dir=tmp, ambience_fallback=False,
                )
            self.assertTrue(kwargs.get("sustained"))

    def test_ambience_miss_synthesizes_fallback_bed(self):
        from pydub import AudioSegment

        import llm_from_here.plugins.foleyAgent as foley_mod

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            foley_mod.FoleyAgent, "resolve", return_value={
                "status": "miss",
                "file": None,
                "reason": "no matches",
                "selected": None,
                "audit": {"attempts": []},
            },
        ):
            stt = self._stt(tmp)
            out = os.path.join(tmp, "bg.wav")
            res = stt.music_generator_foley_ambience(
                "[BACKGROUND: inscrutable din]", out, cache_dir=tmp
            )
            self.assertTrue(res)
            self.assertTrue(os.path.isfile(out))
            seg = AudioSegment.from_wav(out)
            self.assertGreaterEqual(len(seg) / 1000.0, 40.0)
            self.assertGreater(seg.max_dBFS, -60.0)

    def test_ambience_no_fallback_skips_segment(self):
        import llm_from_here.plugins.foleyAgent as foley_mod

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            foley_mod.FoleyAgent, "resolve", return_value={
                "status": "miss",
                "file": None,
                "reason": "no matches",
                "selected": None,
                "audit": {"attempts": []},
            },
        ):
            stt = self._stt(tmp)
            out = os.path.join(tmp, "bg.wav")
            res = stt.music_generator_foley_ambience(
                "[BACKGROUND: inscrutable din]", out, cache_dir=tmp, ambience_fallback=False
            )
            self.assertIsNone(res)
            self.assertFalse(os.path.exists(out))

    def test_audit_records_attempts_at_top_level(self):
        import json as _json

        import llm_from_here.plugins.foleyAgent as foley_mod

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            foley_mod.FoleyAgent, "resolve", return_value={
                "status": "hit",
                "file": os.path.join(tmp, "dl.mp3"),
                "reason": None,
                "selected": {"provider": "freesound", "id": 9, "name": "Thump"},
                "attempts": [
                    {"attempt": 1, "query": "stamp", "candidates": [], "decision": "retry"},
                ],
            },
        ):
            with open(os.path.join(tmp, "dl.mp3"), "wb") as f:
                f.write(b"audio")
            stt = self._stt(tmp)
            stt.music_generator_foley_agent("stamp thump", os.path.join(tmp, "o.wav"), cache_dir=tmp)
            rows = _json.load(open(os.path.join(tmp, "foley_audit.json")))
            self.assertEqual(rows[0]["attempts"][0]["query"], "stamp")

    def test_cue_stripping(self):
        with tempfile.TemporaryDirectory() as tmp:
            stt = self._stt(tmp)
            self.assertEqual(stt._foley_cue_query("[SFX: door creak]"), "door creak")
            self.assertEqual(stt._foley_cue_query("[BACKGROUND: cafe ambience]"), "cafe ambience")
            self.assertEqual(stt._foley_cue_query("plain cue"), "plain cue")


class TestSfxCapPerTurn(unittest.TestCase):
    @patch("llm_from_here.plugins.improvAgent.LlmSession")
    @patch("llm_from_here.plugins.improvAgent.FreeSoundFetch")
    def test_more_than_cap_cues_are_truncated(self, _mock_fs: MagicMock, _mock_llm: MagicMock):
        with tempfile.TemporaryDirectory() as tmp:
            params = {
                "setup_model": "openrouter:deepseek/deepseek-v4-flash",
                "character_slots": [
                    {"model": "openrouter:deepseek/deepseek-v4-flash"}
                ],
            }
            agent = ImprovAgent(params, {"output_folder": tmp}, "improv")
            turn = ImprovTurn(
                dialog="Hi", sfx_cues=["a", "b", "c", "d"]
            )
            segs = agent._sfx_segments_for_turn(turn, turn_index=0)
            self.assertLessEqual(len(segs), _MAX_SFX_CUES_PER_TURN)
            self.assertEqual(2, len(segs))
            self.assertTrue(any(row.get("truncated") for row in agent.audit_log))

    @patch("llm_from_here.plugins.improvAgent.LlmSession")
    @patch("llm_from_here.plugins.improvAgent.FreeSoundFetch")
    def test_within_cap_cues_kept(self, _mock_fs: MagicMock, _mock_llm: MagicMock):
        with tempfile.TemporaryDirectory() as tmp:
            params = {
                "setup_model": "openrouter:deepseek/deepseek-v4-flash",
                "character_slots": [
                    {"model": "openrouter:deepseek/deepseek-v4-flash"}
                ],
            }
            agent = ImprovAgent(params, {"output_folder": tmp}, "improv")
            turn = ImprovTurn(dialog="Hi", sfx_cues=["cup clink", ""])
            segs = agent._sfx_segments_for_turn(turn, turn_index=0)
            self.assertEqual(len(segs), 1)
            self.assertEqual(segs[0]["sfx_search_query"], "cup clink")


class TestImprovDefaults(unittest.TestCase):
    @patch("llm_from_here.plugins.improvAgent.LlmSession")
    @patch("llm_from_here.plugins.improvAgent.FreeSoundFetch")
    def test_default_type_map_uses_ambience_and_sfx_cap(self, _mock_fs, _mock_llm):
        self.assertEqual(
            _DEFAULT_SFX_MAP["background"]["segment_type"],
            "music_generator_foley_ambience",
        )
        self.assertTrue(_DEFAULT_SFX_MAP["background"]["background_music"])
        self.assertEqual(
            _DEFAULT_SFX_MAP["sound effect"]["arguments"]["foley_max_duration_sec"], 12
        )
        with tempfile.TemporaryDirectory() as tmp:
            params = {
                "setup_model": "openrouter:deepseek/deepseek-v4-flash",
                "character_slots": [
                    {"model": "openrouter:deepseek/deepseek-v4-flash", "tts_voice": "Puck"},
                    {"model": "openrouter:deepseek/deepseek-v4-flash", "tts_voice": "Fenrir"},
                ],
            }
            agent = ImprovAgent(params, {"output_folder": tmp}, "improv")
            scene = SceneSetup(
                characters=[
                    {"slot": 1, "name": "Deirdre", "description": "librarian"},
                    {"slot": 2, "name": "Marlon", "description": "mycology obsessive"},
                ],
                setting="library before storytime",
                scenario="cataloguing donations",
                background_sound="quiet library hum",
                sfx_palette=["tape rip", "stamp thump"],
            )
            seg_map = agent._build_segment_type_map(scene)
            self.assertEqual(
                seg_map["background"]["segment_type"], "music_generator_foley_ambience"
            )
            self.assertEqual(
                seg_map["sound effect"]["arguments"]["foley_max_duration_sec"], 12
            )
            self.assertEqual(seg_map["character 1"]["arguments"]["voice"], "Puck")

    @patch("llm_from_here.plugins.improvAgent.LlmSession")
    @patch("llm_from_here.plugins.improvAgent.FreeSoundFetch")
    def test_scene_establishment_rule_is_appended_to_slots(self, _mock_fs, _mock_llm):
        with tempfile.TemporaryDirectory() as tmp:
            params = {
                "setup_model": "openrouter:deepseek/deepseek-v4-flash",
                "character_slots": [
                    {"model": "openrouter:deepseek/deepseek-v4-flash", "system_message": "BE FUNNY."},
                ],
            }
            agent = ImprovAgent(params, {"output_folder": tmp}, "improv")
            slot_prompt = _mock_llm.call_args_list[1].args[0]
            self.assertTrue(slot_prompt.startswith("BE FUNNY."))
            self.assertIn(
                "Establish the scene in the opening exchange.", slot_prompt
            )

    @patch("llm_from_here.plugins.improvAgent.LlmSession")
    @patch("llm_from_here.plugins.improvAgent.FreeSoundFetch")
    def test_scene_establishment_can_be_disabled_and_overridden(self, _mock_fs, _mock_llm):
        with tempfile.TemporaryDirectory() as tmp:
            params = {
                "setup_model": "openrouter:deepseek/deepseek-v4-flash",
                "scene_establishment": False,
                "character_slots": [
                    {"model": "openrouter:deepseek/deepseek-v4-flash", "system_message": "X"},
                ],
            }
            agent = ImprovAgent(params, {"output_folder": tmp}, "improv")
            self.assertEqual(_mock_llm.call_args_list[1].args[0], "X")

        _mock_llm.reset_mock()
        with tempfile.TemporaryDirectory() as tmp:
            params = {
                "setup_model": "openrouter:deepseek/deepseek-v4-flash",
                "scene_establishment_instruction": "Say where you are first.",
                "character_slots": [
                    {"model": "openrouter:deepseek/deepseek-v4-flash", "system_message": "X"},
                ],
            }
            agent = ImprovAgent(params, {"output_folder": tmp}, "improv")
            prompt = _mock_llm.call_args_list[1].args[0]
            self.assertIn("Say where you are first.", prompt)
            self.assertNotIn("opening exchange", prompt)


if __name__ == "__main__":
    unittest.main()