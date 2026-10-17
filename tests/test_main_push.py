"""main.send_file_to_chats: every operator chat gets the file."""

from __future__ import annotations

import asyncio

import pytest

import main as main_mod


class _Bot:
    def __init__(self, refuse=()):
        self.refuse = set(refuse)
        self.sent: list[tuple[str, int]] = []

    async def _send(self, how, chat_id, fh, **kw):
        if chat_id in self.refuse:
            raise RuntimeError(f"chat {chat_id} blocked the bot")
        assert fh.read() == b"clip"
        self.sent.append((how, chat_id))

    async def send_video(self, chat_id, fh, **kw):
        await self._send("video", chat_id, fh, **kw)

    async def send_photo(self, chat_id, fh, **kw):
        await self._send("photo", chat_id, fh, **kw)

    async def send_document(self, chat_id, fh, **kw):
        await self._send("document", chat_id, fh, **kw)


def test_one_chat_that_fails_does_not_stop_the_rest(tmp_path):
    clip = tmp_path / "proof.mp4"
    clip.write_bytes(b"clip")
    bot = _Bot(refuse={1})
    with pytest.raises(RuntimeError, match="chat 1"):
        asyncio.run(main_mod.send_file_to_chats(bot, [1, 2, 3], clip, "video"))
    assert bot.sent == [("video", 2), ("video", 3)]


def test_every_chat_gets_it_and_nothing_is_raised(tmp_path):
    still = tmp_path / "thumb.png"
    still.write_bytes(b"clip")
    bot = _Bot()
    asyncio.run(main_mod.send_file_to_chats(bot, [5, 6], still, "photo",
                                            caption="x" * 2000))
    assert bot.sent == [("photo", 5), ("photo", 6)]
