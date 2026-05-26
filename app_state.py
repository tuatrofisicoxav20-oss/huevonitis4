import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppState:
    current_project: Any | None = None
    current_page_index: int = 0
    selected_element_id: str | None = None
    active_view: str = "dashboard"
    sidebar_expanded: bool = True
    unsaved_changes: bool = False
    status_message: str = ""
    current_tool: str = "select"
    zoom_level: float = 1.0
    current_job_id: str | None = None
    study_text: str = ""
    study_bundle: Any | None = None
    study_document: Any | None = None  # Document estructurado del último import en Study
    inkcore_image_path: str | None = None
    inkcore_extracted_glyphs: list = field(default_factory=list)
    # v4.2: perfil de letra activo. Se persiste a settings.json desde main_view.
    active_profile_id: str = "default"

    def __post_init__(self):
        # Lock for thread-safe access when background workers read/write state.
        # All UI mutations must happen on the main thread (via widget.after()).
        self._lock: threading.Lock = threading.Lock()

    def mark_changed(self):
        self.unsaved_changes = True

    def mark_saved(self):
        self.unsaved_changes = False


STATE = AppState()
