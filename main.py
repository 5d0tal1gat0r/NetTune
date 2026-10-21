"""Entry point for the scan pipeline: python main.py (what the systemd unit runs).

The code lives in the nettune/ package; this file only starts it, so the
service, the deploy scripts and the release check keep using main.py.
"""

from nettune.main import main

if __name__ == "__main__":
    main()
