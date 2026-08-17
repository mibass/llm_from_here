"""Unit tests for the FoleyAgent (LLM-in-the-loop SFX resolver)."""

from __future__ import annotations

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
from llm_from_here.plugins.improvAgent import ImprovAgent, _MAX_SFX_CUES_PER_TURN
from llm_from_here.plugins.segmentsToTimeline import SegmentsToTimeline
from llm_from_here.schemas.improv_outputs import ImprovTurn


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

    def test_repeated_refined_query_gives_up(self):
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
            self.assertEqual(res["status"], "miss")
            self.assertIn("repeated", res["reason"] or "")

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

    def test_bogus_accepted_ref_gives_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = _FakeProvider(_cand("1", "One", 1.0))
            agent = self._agent(tmp, [prov], [{"accept": True, "candidate_ref": "fake:999"}])
            res = agent.resolve("thing")
            self.assertEqual(res["status"], "miss")

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


if __name__ == "__main__":
    unittest.main()