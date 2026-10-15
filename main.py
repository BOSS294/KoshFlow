"""KoshFlow desktop launcher.

Purpose: Launch the KoshFlow desktop billing and PDF Studio application from a source checkout.
Project: KoshFlow | Version: 0.6.3
Developer: Mayank Chawdhari AKA BOSS294
Integration: Run `python main.py` from the project root after installing requirements.
Changelog: v0.6.3 — Public release documentation and Windows packaging metadata aligned with the current application version.
"""

from koshflow.app import run

if __name__ == "__main__":
    raise SystemExit(run())
