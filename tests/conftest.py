"""Test setup: InniSync keeps its data in a throwaway folder (INNISYNC_DATA is read when the modules load), and the
package is importable from the repo root."""
import os
import sys
import tempfile

os.environ["INNISYNC_DATA"] = tempfile.mkdtemp(prefix="innisync-test-")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
