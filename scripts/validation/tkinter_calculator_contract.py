"""Fixed live acceptance: actual Tk widgets, no model calls or source repair."""
import argparse
import importlib.util
from pathlib import Path
import sys
import tkinter as tk
import unittest


def validate(project):
    project = Path(project).resolve()
    source = project / "calculator.py"
    if not source.is_file() or not source.resolve().is_relative_to(project):
        raise ValueError("Expected a workspace-local calculator.py")
    spec = importlib.util.spec_from_file_location("live_calculator", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class CalculatorContract(unittest.TestCase):
        def setUp(self):
            self.root = tk.Tk()
            self.addCleanup(self.root.destroy)
            self.root.title("LCA controlled Tk calculator acceptance")
            self.app = module.Calculator(self.root)
            self.app.pack()
            self.root.update()
            self.assertIsInstance(self.app.display_var, tk.StringVar)

        def press(self, *labels):
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            for label in labels:
                buttons = [w for w in descendants(self.app)
                           if "text" in w.keys() and str(w.cget("text")) == label and hasattr(w, "invoke")]
                self.assertEqual(len(buttons), 1, "Expected one button: " + label)
                buttons[0].invoke()
                self.root.update()
            return self.app.display_var.get()

        def test_add(self): self.assertEqual(float(self.press("1", "+", "2", "=")), 3)
        def test_subtract(self): self.assertEqual(float(self.press("9", "-", "4", "=")), 5)
        def test_multiply(self): self.assertEqual(float(self.press("6", "*", "7", "=")), 42)
        def test_divide(self): self.assertEqual(float(self.press("8", "/", "2", "=")), 4)
        def test_decimal(self): self.assertAlmostEqual(float(self.press("1", ".", "5", "+", "2", "=")), 3.5)
        def test_clear(self): self.assertIn(self.press("1", "2", "C"), ("", "0"))
        def test_zero_division(self): self.assertIn("error", self.press("1", "/", "0", "=").lower())
        def test_invalid_expression(self): self.assertIn("error", self.press("+", "=").lower())

    return unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(CalculatorContract)).wasSuccessful()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if validate(args.project) else 1)
