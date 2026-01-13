import sys
import os

# #region agent log
import json
from datetime import datetime
def debug_log(location, message, data=None, hypothesis_id=None):
    try:
        log_entry = {
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        with open("/home/kei/PythonProject/NeoBookMarkManager/.cursor/debug.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except:
        pass
# #endregion

debug_log("main.py:1", "Script started", {}, "H1")

# Ensure the core/gui/services modules are importable
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
debug_log("main.py:8", "sys.path updated", {}, "H1")

try:
    debug_log("main.py:11", "Before importing App class", {}, "H2")
    from gui.main_window import App
    debug_log("main.py:13", "App class imported successfully", {}, "H2")
except Exception as e:
    import traceback
    debug_log("main.py:15", "Import error", {"error": str(e), "traceback": traceback.format_exc()}, "H2")
    raise
except SystemExit:
    debug_log("main.py:18", "SystemExit during import", {}, "H2")
    raise
except:
    import traceback
    debug_log("main.py:21", "Unexpected error during import", {"traceback": traceback.format_exc()}, "H2")
    raise

if __name__ == "__main__":
    try:
        debug_log("main.py:26", "Before creating App instance", {}, "H3")
        app = App()
        debug_log("main.py:28", "App instance created successfully", {}, "H3")
        
        debug_log("main.py:30", "Before starting mainloop", {}, "H4")
        app.mainloop()
        debug_log("main.py:32", "Mainloop exited", {}, "H4")
    except SystemExit:
        debug_log("main.py:35", "SystemExit during execution", {}, "H3")
        raise
    except Exception as e:
        import traceback
        debug_log("main.py:38", "Exception during app creation or mainloop", {"error": str(e), "traceback": traceback.format_exc()}, "H3")
        raise
    except:
        import traceback
        debug_log("main.py:42", "Unexpected error", {"traceback": traceback.format_exc()}, "H3")
        raise
