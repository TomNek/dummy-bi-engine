"""Story/Navigation Layer — Phase 23E.

CRUD endpoints for stories + slide apply/capture.
Stories are ordered sequences of slides, each with an embedded state snapshot
(same schema as bookmarks: page_id + filters + slicer_selections +
interaction_selections + visual_visibility).

Key design:
- "Capture Current View" is the primary workflow — users explore, then capture.
- `captured_state` > `bookmark_id` > empty (resolution order for apply_slide).
- apply_slide never writes to disk (Save-only persistence).
- capture_slide writes to stories.yaml (explicit save action).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any, Optional

from fastapi import Body

from dax_project.save import load_stories, save_stories, load_bookmarks
from dax_ui.server import _json_safe_with_path, _validate_safe_name
from dax_ui.server._runtime_helpers import _resolve_project_path_runtime

logger = logging.getLogger(__name__)


def _ok(data: Any) -> dict:
    return {"ok": True, **data}


def _err(status: int, msg: str, error_code: str = "E_STORY") -> dict:
    from fastapi.responses import JSONResponse
    logger.warning("Story request failed (%s): %s", error_code, msg)
    return JSONResponse(
        status_code=status,
        content={"ok": False, "error": error_code, "message": "Story request failed"},
    )


def register_story_routes(app: Any) -> None:
    """Register story CRUD + slide apply/capture endpoints."""

    # ------------------------------------------------------------------
    # GET /runtime/stories — list all stories
    # ------------------------------------------------------------------
    @app.get("/runtime/stories")
    def get_stories(project: Optional[str] = None):
        """List all stories."""
        try:
            project_path = _resolve_project_path_runtime(project)
            data = load_stories(project_path)
            return _ok(data)
        except Exception as exc:
            return _err(400, str(exc))

    # ------------------------------------------------------------------
    # POST /runtime/stories — create a new story
    # ------------------------------------------------------------------
    @app.post("/runtime/stories")
    def create_story(
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Create a new story (append to list, persist immediately)."""
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("story payload must be an object")

            story = safe.get("story")
            if not isinstance(story, Mapping):
                raise ValueError("story object is required")

            # Validate story name
            st_name = str(story.get("name") or "").strip()
            if st_name:
                _validate_safe_name(st_name, label="story name")

            existing = load_stories(project_path)
            stories = list(existing.get("stories") or [])

            # Ensure unique id
            new_id = str(story.get("id") or "").strip()
            if not new_id:
                new_id = str(uuid.uuid4())
                story = dict(story, id=new_id)

            for s in stories:
                if str(s.get("id") or "").strip().upper() == new_id.upper():
                    raise ValueError(f"Story with id {new_id!r} already exists")

            stories.append(dict(story))
            result = save_stories(project_path, {"stories": stories})
            return _ok(result)
        except Exception as exc:
            return _err(400, str(exc))

    # ------------------------------------------------------------------
    # PUT /runtime/stories/{story_id} — update a story
    # ------------------------------------------------------------------
    @app.put("/runtime/stories/{story_id}")
    def update_story(
        story_id: str,
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Update a story by id (name, slides, order)."""
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("story payload must be an object")

            story = safe.get("story")
            if not isinstance(story, Mapping):
                raise ValueError("story object is required")

            # Validate story name
            st_name = str(story.get("name") or "").strip()
            if st_name:
                _validate_safe_name(st_name, label="story name")

            existing = load_stories(project_path)
            stories = list(existing.get("stories") or [])

            target_key = story_id.strip().upper()
            found = False
            for i, s in enumerate(stories):
                if str(s.get("id") or "").strip().upper() == target_key:
                    updated = dict(story, id=story_id.strip())
                    stories[i] = updated
                    found = True
                    break

            if not found:
                raise ValueError(f"Story {story_id!r} not found")

            result = save_stories(project_path, {"stories": stories})
            return _ok(result)
        except Exception as exc:
            return _err(400, str(exc))

    # ------------------------------------------------------------------
    # DELETE /runtime/stories/{story_id} — delete a story
    # ------------------------------------------------------------------
    @app.delete("/runtime/stories/{story_id}")
    def delete_story(
        story_id: str,
        project: Optional[str] = None,
    ):
        """Delete a story by id."""
        try:
            project_path = _resolve_project_path_runtime(project)
            existing = load_stories(project_path)
            stories = list(existing.get("stories") or [])

            target_key = story_id.strip().upper()
            new_list = [
                s for s in stories
                if str(s.get("id") or "").strip().upper() != target_key
            ]

            if len(new_list) == len(stories):
                raise ValueError(f"Story {story_id!r} not found")

            result = save_stories(project_path, {"stories": new_list})
            return _ok({"deleted": story_id.strip(), **result})
        except Exception as exc:
            return _err(400, str(exc))

    # ------------------------------------------------------------------
    # POST /runtime/stories/{story_id}/apply_slide — resolve slide state
    # ------------------------------------------------------------------
    @app.post("/runtime/stories/{story_id}/apply_slide")
    def apply_slide(
        story_id: str,
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Resolve and return the state for a specific slide.

        Payload: { slide_id: string }

        Resolution order:
          1. captured_state (inline snapshot) → return directly
          2. bookmark_id → resolve bookmark state and return
          3. empty → return { page_id } only (default page state)

        Does NOT persist anything (Save-only).
        """
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            slide_id = str(safe.get("slide_id") or "").strip()
            if not slide_id:
                raise ValueError("slide_id is required")

            existing = load_stories(project_path)
            stories = list(existing.get("stories") or [])

            # Find story
            target_story_key = story_id.strip().upper()
            story = None
            for s in stories:
                if str(s.get("id") or "").strip().upper() == target_story_key:
                    story = s
                    break

            if story is None:
                raise ValueError(f"Story {story_id!r} not found")

            # Find slide
            slides = list(story.get("slides") or [])
            target_slide_key = slide_id.upper()
            slide = None
            for sl in slides:
                if str(sl.get("id") or "").strip().upper() == target_slide_key:
                    slide = sl
                    break

            if slide is None:
                raise ValueError(f"Slide {slide_id!r} not found in story {story_id!r}")

            page_id = str(slide.get("page_id") or "").strip()

            # Resolution order: captured_state > bookmark_id > empty
            captured = slide.get("captured_state")
            if isinstance(captured, Mapping) and captured:
                state = {
                    "page_id": page_id,
                    "filters": captured.get("filters", []),
                    "slicer_selections": captured.get("slicer_selections", {}),
                    "interaction_selections": captured.get("interaction_selections", []),
                    "visual_visibility": captured.get("visual_visibility", {}),
                }
                return _ok({"slide": slide, "state": state, "source": "captured_state"})

            bookmark_id = str(slide.get("bookmark_id") or "").strip()
            if bookmark_id:
                # Resolve bookmark state
                try:
                    bookmarks_data = load_bookmarks(project_path)
                    bookmarks = list(bookmarks_data.get("bookmarks") or [])
                    bk_key = bookmark_id.upper()
                    bk = None
                    for b in bookmarks:
                        if str(b.get("id") or "").strip().upper() == bk_key:
                            bk = b
                            break

                    if bk is None:
                        raise ValueError(f"Bookmark {bookmark_id!r} referenced by slide {slide_id!r} not found")

                    state = {
                        "page_id": page_id or str(bk.get("current_page_id") or ""),
                        "filters": bk.get("filters", []),
                        "slicer_selections": bk.get("slicer_selections", {}),
                        "interaction_selections": bk.get("interaction_selections", []),
                        "visual_visibility": bk.get("visual_visibility", {}),
                    }
                    return _ok({"slide": slide, "state": state, "source": "bookmark"})
                except Exception as bk_exc:
                    return _err(400, f"Failed to resolve bookmark for slide: {bk_exc}", "E_STORY_BOOKMARK")

            # Empty state — just page navigation
            state = {
                "page_id": page_id,
                "filters": [],
                "slicer_selections": {},
                "interaction_selections": [],
                "visual_visibility": {},
            }
            return _ok({"slide": slide, "state": state, "source": "empty"})
        except Exception as exc:
            return _err(400, str(exc))

    # ------------------------------------------------------------------
    # POST /runtime/stories/{story_id}/capture_slide — capture current view
    # ------------------------------------------------------------------
    @app.post("/runtime/stories/{story_id}/capture_slide")
    def capture_slide(
        story_id: str,
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Capture current client state into a slide's captured_state.

        Payload:
          {
            slide_id: string,
            page_id: string,
            filters: [...],
            slicer_selections: {...},
            interaction_selections: [...],
            visual_visibility: {...}
          }

        This is an explicit save action — persists to stories.yaml.
        """
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            slide_id = str(safe.get("slide_id") or "").strip()
            if not slide_id:
                raise ValueError("slide_id is required")

            existing = load_stories(project_path)
            stories = list(existing.get("stories") or [])

            # Find story
            target_story_key = story_id.strip().upper()
            story_idx = None
            for i, s in enumerate(stories):
                if str(s.get("id") or "").strip().upper() == target_story_key:
                    story_idx = i
                    break

            if story_idx is None:
                raise ValueError(f"Story {story_id!r} not found")

            # Find slide
            slides = list(stories[story_idx].get("slides") or [])
            target_slide_key = slide_id.upper()
            slide_idx = None
            for j, sl in enumerate(slides):
                if str(sl.get("id") or "").strip().upper() == target_slide_key:
                    slide_idx = j
                    break

            if slide_idx is None:
                raise ValueError(f"Slide {slide_id!r} not found in story {story_id!r}")

            # Build captured_state from payload
            captured_state = {
                "filters": safe.get("filters", []),
                "slicer_selections": safe.get("slicer_selections", {}),
                "interaction_selections": safe.get("interaction_selections", []),
                "visual_visibility": safe.get("visual_visibility", {}),
            }

            # Update slide
            slide = dict(slides[slide_idx])
            slide["captured_state"] = captured_state
            if safe.get("page_id"):
                slide["page_id"] = str(safe["page_id"]).strip()
            slides[slide_idx] = slide

            # Update story
            updated_story = dict(stories[story_idx])
            updated_story["slides"] = slides
            stories[story_idx] = updated_story

            result = save_stories(project_path, {"stories": stories})
            return _ok({"captured": True, **result})
        except Exception as exc:
            return _err(400, str(exc))
