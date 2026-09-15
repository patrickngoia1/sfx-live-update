#!/usr/bin/env python3
"""Where the operator's configuration lives.

NOT inside the plugin. Claude Code installs a plugin into a versioned directory
(cache/<marketplace>/<plugin>/<version>), so every update lands in a new folder
and anything written next to the code would be lost. Configuration therefore
lives in a stable home the user owns.
"""
import os

HOME = os.path.expanduser(
    os.environ.get("SFX_LIVE_UPDATE_HOME", "~/.claude/sfx-live-update"))


def path(name):
    return os.path.join(HOME, name)


def ensure():
    os.makedirs(HOME, exist_ok=True)
    return HOME
