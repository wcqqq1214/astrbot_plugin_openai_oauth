"""Serve generated PNG attachments in a read-only ChatUI message view."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chatui_citations import _CitationRun

from astrbot.core.message.interactive_ui import (
    ViewError,
    ViewResult,
    resolve_view_spec,
    view_store,
)
from astrbot.core.platform.sources.webchat.webchat_queue_mgr import webchat_queue_mgr
from astrbot.dashboard.services.chat_service import ChatService
from astrbot.dashboard.services.plugin_page_service import (
    PluginPageContentPayload,
    PluginPageService,
    PluginPageServiceError,
)

PLUGIN = "astrbot_plugin_openai_oauth"
MODULE = __package__.rsplit(".", 1)[0] + ".main"
VIEW = "image_progress"


@dataclass
class ImageCard:
    id: str
    state: _CitationRun
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    submitted: bool = False

    @property
    def part(self) -> dict:
        return {
            "type": "view",
            "id": self.id,
            "name": VIEW,
            "target": "chat_message",
            "title": "GPT Image",
            "text": "0%",
        }

    async def deliver(self, image: bytes) -> None:
        state = self.state
        filename = f"codex-{self.id}.png"
        path = Path(state.service.attachments_dir) / filename
        attachment = None
        try:
            with path.open("xb") as output:
                await asyncio.to_thread(output.write, image)
            attachment = await state.service.create_attachment_from_file(
                filename, "image"
            )
            if not attachment:
                raise OSError("Could not register the generated image")
            self.submitted = await webchat_queue_mgr.put_back_queue(
                state.run.run_id,
                {
                    "type": "view",
                    "data": {
                        **self.part,
                        "attachment_id": attachment["attachment_id"],
                        "filename": filename,
                        "text": "GPT Image",
                    },
                    "message_id": state.run.run_id,
                },
            )
            if not self.submitted:
                raise OSError("Chat closed before image delivery")
        finally:
            if not self.submitted:
                path.unlink(missing_ok=True)
                if attachment:
                    await state.service.db.delete_attachment(
                        attachment["attachment_id"]
                    )
        self.ready.set()


async def create(state: _CitationRun) -> ImageCard:
    _, spec = resolve_view_spec(MODULE, VIEW)
    run = state.run
    save = asyncio.create_task(
        asyncio.to_thread(
            view_store.create,
            MODULE,
            spec,
            ViewResult(name=VIEW, data={}, text="0%"),
            owner=run.username,
            session_id=run.session_id,
            platform_id="webchat",
            history_platform_id=run.platform_history_id,
            run_id=run.run_id,
        )
    )
    try:
        record = await asyncio.shield(save)
    except asyncio.CancelledError:
        record = await save
        await asyncio.to_thread(discard_unbound, record["id"])
        raise
    return ImageCard(record["id"], state)


def discard_unbound(view_id: str) -> None:
    with view_store.connect() as db:
        db.execute(
            "DELETE FROM interactive_views WHERE id=? AND message_id IS NULL",
            (view_id,),
        )


def install(active_runs):
    # Chat views have scoped asset URLs. Reuse the host's conversation/view
    # authorization on the PNG request as well as the initial HTML request.
    get_view = ChatService.get_chat_view
    serve = PluginPageService.serve_page_content
    roots = PluginPageService.resolve_plugin_pages_root
    chat = None

    @wraps(get_view)
    async def get_chat_view(self, username, view_id):
        nonlocal chat
        result = await get_view(self, username, view_id)
        if result[0]["module"] == MODULE and result[0]["name"] == VIEW:
            chat = self
        return result

    @wraps(roots)
    async def pages_root(self, plugin):
        # The host picks just one root when pages/ and views/ coexist.
        # Keep the existing Providers page available on old and new hosts.
        if plugin.name == PLUGIN:
            return self.get_plugin_root_dir(plugin) / "pages"
        return await roots(self, plugin)

    @wraps(serve)
    async def serve_content(
        self, *, plugin_name, view_name, asset_path, username, **kwargs
    ):
        if (plugin_name, view_name) != (PLUGIN, VIEW):
            return await serve(
                self,
                plugin_name=plugin_name,
                view_name=view_name,
                asset_path=asset_path,
                username=username,
                **kwargs,
            )
        match = re.fullmatch(r"([0-9a-f]{32})\.png", asset_path)
        if not match or chat is None:
            raise PluginPageServiceError("Image unavailable", status_code=404)
        view_id = match[1]
        try:
            record, _, _, _ = await get_view(chat, username, view_id)
        except ViewError as exc:
            raise PluginPageServiceError("Image unavailable", status_code=404) from exc
        if record["module"] != MODULE or record["name"] != VIEW:
            raise PluginPageServiceError("Image unavailable", status_code=404)
        state = active_runs.get(record["run_id"])
        if state and (card := state.image_cards.get(view_id)):
            await card.ready.wait()
            if not card.submitted:
                raise PluginPageServiceError("Image cancelled", status_code=410)
        path = Path(chat.attachments_dir) / f"codex-{view_id}.png"
        try:
            image = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise PluginPageServiceError("Image unavailable", status_code=404) from exc
        return PluginPageContentPayload(content=image, content_type="image/png")

    hooks = (
        (ChatService, "get_chat_view", get_chat_view, get_view),
        (PluginPageService, "resolve_plugin_pages_root", pages_root, roots),
        (PluginPageService, "serve_page_content", serve_content, serve),
    )
    for owner, name, hook, _ in hooks:
        setattr(owner, name, hook)

    def remove():
        for owner, name, hook, original in hooks:
            if getattr(owner, name) is hook:
                setattr(owner, name, original)

    return remove
