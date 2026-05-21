import threading
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class AppState:
    current_project: Optional[Any] = None
    current_page_index: int = 0
    selected_element_id: Optional[str] = None
    active_view: str = "dashboard"
    sidebar_expanded: bool = True
    unsaved_changes: bool = False
    status_message: str = ""
    current_tool: str = "select"
    zoom_level: float = 1.0
    current_job_id: Optional[str] = None
    study_text: str = ""
    study_bundle: Optional[Any] = None
    inkcore_image_path: Optional[str] = None
    inkcore_extracted_glyphs: list = field(default_factory=list)

    def __post_init__(self):
        # Lock for thread-safe access when background workers read/write state.
        # All UI mutations must happen on the main thread (via widget.after()).
        self._lock: threading.Lock = threading.Lock()

    def mark_changed(self):
        self.unsaved_changes = True

    def mark_saved(self):
        self.unsaved_changes = False


STATE = AppState()
