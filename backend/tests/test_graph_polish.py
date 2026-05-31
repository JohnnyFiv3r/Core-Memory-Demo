"""Static guards for the ReaGraph visual polish (camera + theme + glow).

Keeps the 3D graph on reagraph (no library swap) while adding: a slow idle
auto-rotate that stops on first user interaction, a polished dark theme, and a
bloom/glow pass on the standalone graph view.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ROOT = Path(__file__).resolve().parents[2] / "frontend"
_SLICE = (_ROOT / "public" / "chat-slices" / "graph-3d-runtime.js").read_text()
_CHAT = (_ROOT / "public" / "chat-app.js").read_text()
_GRAPH_MAIN = (_ROOT / "src" / "graph-main.tsx").read_text()
_ENHANCE = (_ROOT / "src" / "graph-enhancements.tsx").read_text()
_PKG = (_ROOT / "package.json").read_text()


class TestSlowAutoRotateSlice(unittest.TestCase):
    def test_slice_drives_own_rotation_and_yields_to_user(self):
        # cameraMode is 'pan' (not the hardcoded-fast built-in 'orbit'); we drive
        # azimuthAngle ourselves and stop on the controls 'control' event.
        self.assertIn("cameraMode: 'pan'", _SLICE)
        self.assertIn("getControls", _SLICE)
        self.assertIn("azimuthAngle", _SLICE)
        self.assertIn("'control'", _SLICE)
        self.assertNotIn("cameraMode: 'orbit'", _SLICE)

    def test_slice_cleans_up_rotation_on_unmount(self):
        self.assertIn("startSlowAutoRotate", _SLICE)
        self.assertIn("__cmUnmount", _SLICE)


class TestStandaloneGraphEnhancements(unittest.TestCase):
    def test_uses_camera_hook_and_bloom_child(self):
        self.assertIn("useSlowAutoRotate", _GRAPH_MAIN)
        self.assertIn("<GraphGlow />", _GRAPH_MAIN)
        self.assertIn('cameraMode="pan"', _GRAPH_MAIN)
        self.assertNotIn('cameraMode="rotate"', _GRAPH_MAIN)

    def test_enhancements_export_hook_and_glow(self):
        self.assertIn("export function useSlowAutoRotate", _ENHANCE)
        self.assertIn("export function GraphGlow", _ENHANCE)
        self.assertIn("@react-three/postprocessing", _ENHANCE)
        self.assertIn("addEventListener('control'", _ENHANCE)

    def test_postprocessing_dep_added(self):
        self.assertIn("@react-three/postprocessing", _PKG)
        self.assertIn('"three"', _PKG)


class TestPolishedThemeShared(unittest.TestCase):
    def test_both_views_use_polished_active_fill(self):
        # The bloom-catching active fill is present in both the inspector slice
        # theme (in chat-app.js) and the standalone view.
        self.assertIn("#8effa6", _CHAT)
        self.assertIn("#8effa6", _GRAPH_MAIN)


if __name__ == "__main__":
    unittest.main()
