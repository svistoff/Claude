"""Тесты папок чатов: создание, перемещение, удаление (чаты сохраняются)."""

from __future__ import annotations

from app.database import repo


def test_folder_crud_and_move():
    fid = repo.create_folder("Работа")
    assert any(f["id"] == fid for f in repo.list_folders())

    conv = repo.create_conversation("demo", "задача")
    assert repo.move_conversation(conv, fid) is True

    chats = {c["id"]: c for c in repo.list_conversations()}
    assert chats[conv]["folder_id"] == fid

    # переименование
    assert repo.rename_folder(fid, "Проекты") is True
    assert any(f["name"] == "Проекты" for f in repo.list_folders())

    # удаление папки — чат остаётся, выходит из папки
    assert repo.delete_folder(fid) is True
    chats = {c["id"]: c for c in repo.list_conversations()}
    assert chats[conv]["folder_id"] is None
    assert repo.get_conversation(conv) is not None


def test_move_to_unknown_folder_fails():
    conv = repo.create_conversation("demo", "x")
    assert repo.move_conversation(conv, "nope") is False


def test_move_to_none():
    fid = repo.create_folder("tmp")
    conv = repo.create_conversation("demo", "y")
    repo.move_conversation(conv, fid)
    assert repo.move_conversation(conv, None) is True
    chats = {c["id"]: c for c in repo.list_conversations()}
    assert chats[conv]["folder_id"] is None
