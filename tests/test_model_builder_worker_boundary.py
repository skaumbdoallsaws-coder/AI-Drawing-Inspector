"""Real isolated-process refusals/containment; no numpy/pytest needed by these tests."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tests.model_builder_test_support import include, module, recipe
from tests.test_model_builder_protocol import ALLOWED, inputs, recipe_60001

errors = module("errors")
shared = module("imports").module("runner")
ImportErrorType = module("imports").module("errors").ModelImportError
normalize = module("recipe").normalize_recipe


class WorkerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mb1b-worker-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.job = self.root / "job"
        self.job.mkdir()
        self.dependencies = self.root / "dependencies"
        self.dependencies.mkdir()
        inputs(self.job)

    def launch(self, **kwargs):
        return shared._launch(self.job, self.dependencies, "build", threading.Event(), 10,
                              build_error_decoder=errors.decode_error, **kwargs)

    def refusal(self, code, path):
        with self.assertRaises(errors.ModelBuildError) as caught:
            self.launch()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.path, path)
        payload = (self.job / "error.json").read_bytes()
        self.assertLessEqual(len(payload), errors.ERROR_BYTES)
        self.assertEqual(errors.decode_error(payload).to_dict(), caught.exception.to_dict())
        self.assertFalse((self.job / "result.json").exists())
        self.assertFalse((self.job / "model.glb").exists())
        return caught.exception

    def test_schema_refusal_decodes_from_real_worker(self):
        value = normalize(recipe())
        value["entries"][0]["unknown"] = 1
        (self.job / "recipe.json").write_bytes(errors.json_bytes(value))
        self.refusal("schema_invalid", "$.entries[0].unknown")

    def test_limits_failure_never_bootstraps_builder(self):
        worker = module("imports").module("worker")
        with patch.object(worker, "limit_resources", return_value=False), patch.object(
                worker, "_build", side_effect=AssertionError("builder loaded without limits")):
            self.assertEqual(worker.main(["unread-dependencies", "unread-job", "build"]), 4)

    def test_exact_60001_refusal_decodes_from_real_worker(self):
        (self.job / "recipe.json").write_bytes(errors.json_bytes(recipe_60001()))
        error = self.refusal("budget_exceeded", "$.entries[2]")
        self.assertEqual(error.triangles, 60001)
        self.assertEqual(error.to_dict()["details"]["limit"], 60000)

    def test_include_refuses_before_loading_numerical_dependencies(self):
        (self.job / "recipe.json").write_bytes(errors.json_bytes(normalize(recipe(include()))))
        self.refusal("composition_unavailable", "$.entries[0].include")

    def test_wrong_font_hash_refuses_in_real_worker(self):
        path = self.job / "fonts/Aileron-Regular-subset.ttf"
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
        self.refusal("font_missing", "$.fonts")

    def test_private_packages_isolation_and_no_application_parents(self):
        (self.dependencies / "poison.pth").write_text("import forbidden_hook\n", encoding="utf-8")
        (self.dependencies / "sitecustomize.py").write_text("raise AssertionError('startup hook')\n", encoding="utf-8")
        probe = (
            "import json,os,sys\nfrom pathlib import Path\n"
            "Path('probe.json').write_text(json.dumps({'isolated':sys.flags.isolated,'noSite':sys.flags.no_site,"
            "'noBytecode':sys.dont_write_bytecode,'paths':sys.path,'cwd':str(Path.cwd()),"
            "'parents':[n for n in sys.modules if n=='ai_inspector' or n.startswith('ai_inspector.')],"
            "'builder':'_model_builder_worker' in sys.modules,'importer':'_model_import_worker' in sys.modules,"
            "'leaked':'BUILDER_SYNTHETIC_PRIVATE' in os.environ}))\nraise ImportError('probe finished')\n")
        (self.dependencies / "numpy.py").write_text(probe, encoding="utf-8")
        with patch.dict(os.environ, {"PYTHONPATH": str(self.root), "BUILDER_SYNTHETIC_PRIVATE": "synthetic"}):
            for task in ("build", "inspect", "prepare"):
                with self.subTest(task=task):
                    # This synthetic numpy records interpreter state; no geometry result is claimed.
                    with self.assertRaises(ImportErrorType) as caught:
                        shared._launch(self.job, self.dependencies, task, threading.Event(), 10,
                                       build_error_decoder=errors.decode_error)
                    self.assertEqual(caught.exception.code, "model_runtime_unavailable")
                    value = json.loads((self.job / "probe.json").read_bytes())
                    self.assertEqual(value["isolated"], 1)
                    self.assertEqual(value["noSite"], 1)
                    self.assertTrue(value["noBytecode"])
                    self.assertEqual(value["parents"], [])
                    self.assertTrue(value["importer"])
                    self.assertEqual(value["builder"], task == "build")
                    self.assertNotIn(value["cwd"], value["paths"])
                    self.assertNotIn("", value["paths"])
                    self.assertFalse(value["leaked"])
                    (self.job / "probe.json").unlink()

    def test_cancel_and_wall_timeout_kill_and_join_real_process(self):
        stub = self.root / "sleep_worker.py"
        stub.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        original = subprocess.Popen
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                processes = []
                def capture(*args, **kwargs):
                    process = original(*args, **kwargs)
                    processes.append(process)
                    if timer:
                        timer.start()
                    return process
                event = threading.Event()
                timer = threading.Timer(.2, event.set) if cancel else None
                start = time.monotonic()
                try:
                    with patch.object(shared, "_WORKER", stub), patch.object(shared.subprocess, "Popen", capture):
                        with self.assertRaises(ImportErrorType) as caught:
                            shared._launch(self.job, self.dependencies, "build", event, 5 if cancel else .2,
                                           build_error_decoder=errors.decode_error)
                    self.assertEqual(caught.exception.code, "model_cancelled" if cancel else "model_timeout")
                finally:
                    if timer and timer.ident is not None:
                        timer.join()
                self.assertTrue(processes)
                self.assertIsNotNone(processes[0].poll())
                self.assertLess(time.monotonic()-start, 5)

    def test_import_error_decoding_does_not_accept_builder_errors(self):
        stub = self.root / "error_worker.py"
        error = errors.ModelBuildError("schema_invalid", "$.entries[0]").to_dict()
        stub.write_text("from pathlib import Path\nPath('error.json').write_bytes(" +
                        repr(errors.json_bytes(error)) + ")\nraise SystemExit(2)\n", encoding="utf-8")
        with patch.object(shared, "_WORKER", stub):
            for task in ("inspect", "prepare"):
                with self.subTest(task=task), self.assertRaises(ImportErrorType) as caught:
                    shared._launch(self.job, self.dependencies, task, threading.Event(), 10,
                                   build_error_decoder=errors.decode_error)
                self.assertEqual(caught.exception.code, "model_worker_failed")

    def test_import_refusal_and_250000_limit_keep_original_decoding(self):
        stub = self.root / "import_error_worker.py"
        error = ImportErrorType("model_output_too_complex", {"triangles": 250001,
            "largestParts": [{"key": "p0", "name": "housing", "triangles": 250001}]})
        stub.write_text("from pathlib import Path\nPath('error.json').write_bytes(" +
                        repr(errors.json_bytes(error.to_dict())) + ")\nraise SystemExit(2)\n", encoding="utf-8")
        with patch.object(shared, "_WORKER", stub):
            for task in ("inspect", "prepare"):
                with self.subTest(task=task), self.assertRaises(ImportErrorType) as caught:
                    shared._launch(self.job, self.dependencies, task, threading.Event(), 10,
                                   build_error_decoder=lambda _: self.fail("used builder decoder for import"))
                self.assertEqual(caught.exception.to_dict(), error.to_dict())

    def test_malformed_build_error_is_worker_failure(self):
        stub = self.root / "bad_error_worker.py"
        value = errors.ModelBuildError("budget_exceeded", "$", triangles=60001).to_dict()
        value["details"]["limit"] = 250000
        stub.write_text("from pathlib import Path\nPath('error.json').write_bytes(" +
                        repr(errors.json_bytes(value)) + ")\nraise SystemExit(2)\n", encoding="utf-8")
        with patch.object(shared, "_WORKER", stub), self.assertRaises(ImportErrorType) as caught:
            self.launch()
        self.assertEqual(caught.exception.code, "model_worker_failed")


if __name__ == "__main__":
    unittest.main()
