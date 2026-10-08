from __future__ import annotations

import unittest

import _helpers  # noqa: F401  (puts core/ on sys.path)
from atwlib import junit


def suite(*cases: str) -> str:
    return "<testsuites><testsuite>" + "".join(cases) + "</testsuite></testsuites>"


PY_FAIL = '<testcase classname="tests.test_x" name="test_a"><failure message="AssertionError: assert None == 2"/></testcase>'
PY_IMPORT = '<testcase classname="tests.test_x" name="test_b"><failure message="ImportError: cannot import name \'f\'"/></testcase>'
PY_PASS = '<testcase classname="tests.test_x" name="test_c"/>'
PY_SKIP = '<testcase classname="tests.test_x" name="test_d"><skipped message="later"/></testcase>'
PY_PARAM = '<testcase classname="tests.test_x.TestK" name="test_e[1-2]"><failure message="assert 0"/></testcase>'
TRACE_ONLY = ('<testcase classname="tests.test_x" name="test_f"><failure message="AssertionError: wrong">'
              'Traceback\n  import foo  # ImportError: handled\nAssertionError: wrong</failure></testcase>')


class Pytest(unittest.TestCase):

    def test_behavioral_red_passes(self):
        r = junit.check(suite(PY_FAIL), ["tests/test_x.py::test_a"], "red")
        self.assertTrue(r["passed"])

    def test_import_error_is_weak(self):
        r = junit.check(suite(PY_IMPORT), ["tests/test_x.py::test_b"], "red")
        self.assertFalse(r["passed"])
        self.assertIn("weak red", r["verdicts"]["tests/test_x.py::test_b"]["detail"])

    def test_traceback_body_does_not_make_red_weak(self):
        self.assertTrue(junit.check(suite(TRACE_ONLY), ["tests/test_x.py::test_f"], "red")["passed"])

    def test_passing_test_is_not_red_but_is_green(self):
        self.assertFalse(junit.check(suite(PY_PASS), ["tests/test_x.py::test_c"], "red")["passed"])
        self.assertTrue(junit.check(suite(PY_PASS), ["tests/test_x.py::test_c"], "green")["passed"])

    def test_skipped_and_missing_never_pass(self):
        for mode in ("red", "green"):
            self.assertFalse(junit.check(suite(PY_SKIP), ["tests/test_x.py::test_d"], mode)["passed"])
            self.assertFalse(junit.check(suite(PY_PASS), ["tests/test_x.py::nope"], mode)["passed"])

    def test_class_and_params(self):
        self.assertTrue(junit.check(suite(PY_PARAM), ["tests/test_x.py::TestK::test_e[1-2]"], "red")["passed"])

    def test_empty_set_and_garbage_xml_fail(self):
        self.assertFalse(junit.check(suite(PY_FAIL), [], "red")["passed"])
        self.assertFalse(junit.check("<not xml", ["tests/test_x.py::test_a"], "red")["passed"])


JS_FAIL = ('<testcase classname="src/sum.test.ts" name="sum &gt; adds negatives" file="src/sum.test.ts">'
           '<failure message="AssertionError: expected 1 to be 2"/></testcase>')
JS_WEAK = ('<testcase classname="src/sum.test.ts" name="sum &gt; is exported">'
           '<failure message="TypeError: sum is not a function"/></testcase>')
JS_DUP = ('<testcase classname="a.test.ts" name="works"><failure message="x"/></testcase>'
          '<testcase classname="b.test.ts" name="works"><failure message="x"/></testcase>')


class NameStyle(unittest.TestCase):

    def test_title_with_file(self):
        r = junit.check(suite(JS_FAIL), ["src/sum.test.ts::adds negatives"], "red", "name")
        self.assertTrue(r["passed"], r)

    def test_full_title(self):
        self.assertTrue(junit.check(suite(JS_FAIL), ["sum > adds negatives"], "red", "name")["passed"])

    def test_wrong_file_is_missing(self):
        self.assertFalse(junit.check(suite(JS_FAIL), ["src/other.test.ts::adds negatives"], "red", "name")["passed"])

    def test_js_weak(self):
        self.assertFalse(junit.check(suite(JS_WEAK), ["is exported"], "red", "name")["passed"])

    def test_ambiguous(self):
        r = junit.check(suite(JS_DUP), ["works"], "red", "name")
        self.assertEqual(r["verdicts"]["works"]["outcome"], "ambiguous")
        self.assertTrue(junit.check(suite(JS_DUP), ["a.test.ts::works"], "red", "name")["passed"])


if __name__ == "__main__":
    unittest.main()
