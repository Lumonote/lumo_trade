import subprocess
from pathlib import Path


EXTERNAL_LINK_JS = (
    Path(__file__).resolve().parents[1]
    / "webui"
    / "static"
    / "lumo_open_external.js"
)


def test_external_link_fallback_runs_after_in_app_link_handlers():
    harness = r"""
const fs = require("fs");
let clickCapture;
global.document = {
  body: { dataset: { desktopMode: "1" } },
  addEventListener(type, handler, capture) {
    if (type === "click") clickCapture = capture;
  },
};
global.window = { location: { href: "http://127.0.0.1:7070/desktop" } };
eval(fs.readFileSync(process.argv[1], "utf8"));
if (clickCapture === true) {
  throw new Error("external-link fallback registered in capture phase");
}
"""

    result = subprocess.run(
        ["node", "-e", harness, str(EXTERNAL_LINK_JS)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
