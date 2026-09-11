# PyInstaller runtime hook: import the engine from <bundle>/src/usali, where
# the spec places it as plain source (see open-hospitality.spec).
import os
import sys

sys.path.insert(0, os.path.join(getattr(sys, "_MEIPASS", ""), "src"))
