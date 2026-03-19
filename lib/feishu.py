"""Thin wrapper around lark-oapi for wiki + docx operations."""

import lark_oapi as lark
from lark_oapi.api.wiki.v2 import *
from lark_oapi.api.docx.v1 import (
    ListDocumentBlockRequest,
    RawContentDocumentRequest,
    BatchUpdateDocumentBlockRequest,
    BatchUpdateDocumentBlockRequestBody,
    CreateDocumentBlockChildrenRequest,
    CreateDocumentBlockChildrenRequestBody,
    BatchDeleteDocumentBlockChildrenRequest,
    BatchDeleteDocumentBlockChildrenRequestBody,
    Block,
    Text,
    TextElement,
    TextRun,
)

from . import config


def _client() -> lark.Client:
    return (
        lark.Client.builder()
        .app_id(config.FEISHU_APP_ID)
        .app_secret(config.FEISHU_APP_SECRET)
        .build()
    )


# -- Wiki spaces --

def list_spaces() -> list[dict]:
    req = ListSpaceRequest.builder().page_size(50).build()
    resp = _client().wiki.v2.space.list(req)
    if not resp.success():
        raise RuntimeError(f"list_spaces: {resp.code} {resp.msg}")
    return [{"space_id": s.space_id, "name": s.name} for s in (resp.data.items or [])]


def list_nodes(parent_token: str = "") -> list[dict]:
    b = ListSpaceNodeRequest.builder().space_id(config.FEISHU_WIKI_SPACE_ID).page_size(50)
    if parent_token:
        b = b.parent_node_token(parent_token)
    resp = _client().wiki.v2.space_node.list(b.build())
    if not resp.success():
        raise RuntimeError(f"list_nodes: {resp.code} {resp.msg}")
    return [
        {
            "node_token": n.node_token,
            "obj_token": n.obj_token,
            "title": n.title,
            "obj_type": n.obj_type,
            "has_child": n.has_child,
        }
        for n in (resp.data.items or [])
    ]


def list_nodes_all(parent_token: str = "", space_id: str = "") -> list[dict]:
    """List all direct child nodes with automatic pagination.

    Uses *space_id* if provided, otherwise falls back to config.FEISHU_WIKI_SPACE_ID.
    Fetches all pages transparently via the page_token cursor.
    """
    sid = space_id or config.FEISHU_WIKI_SPACE_ID
    results: list[dict] = []
    page_token = ""
    while True:
        b = ListSpaceNodeRequest.builder().space_id(sid).page_size(50)
        if parent_token:
            b = b.parent_node_token(parent_token)
        if page_token:
            b = b.page_token(page_token)
        resp = _client().wiki.v2.space_node.list(b.build())
        if not resp.success():
            raise RuntimeError(f"list_nodes_all: {resp.code} {resp.msg}")
        for n in resp.data.items or []:
            results.append(
                {
                    "node_token": n.node_token,
                    "obj_token": n.obj_token,
                    "title": n.title,
                    "obj_type": n.obj_type,
                    "has_child": n.has_child,
                }
            )
        if not resp.data.has_more:
            break
        page_token = resp.data.page_token
    return results


def create_node(title: str, parent_token: str = "") -> dict:
    node_b = Node.builder().title(title).obj_type("docx").node_type("origin")
    if parent_token:
        node_b = node_b.parent_node_token(parent_token)
    req = (
        CreateSpaceNodeRequest.builder()
        .space_id(config.FEISHU_WIKI_SPACE_ID)
        .request_body(node_b.build())
        .build()
    )
    resp = _client().wiki.v2.space_node.create(req)
    if not resp.success():
        raise RuntimeError(f"create_node: {resp.code} {resp.msg}")
    n = resp.data.node
    return {"node_token": n.node_token, "obj_token": n.obj_token, "title": n.title}


# -- Document content --

def get_raw_content(document_id: str) -> str:
    req = RawContentDocumentRequest.builder().document_id(document_id).build()
    resp = _client().docx.v1.document.raw_content(req)
    if not resp.success():
        raise RuntimeError(f"get_raw_content: {resp.code} {resp.msg}")
    return resp.data.content


def get_blocks(document_id: str) -> list[dict]:
    req = ListDocumentBlockRequest.builder().document_id(document_id).page_size(500).build()
    resp = _client().docx.v1.document_block.list(req)
    if not resp.success():
        raise RuntimeError(f"get_blocks: {resp.code} {resp.msg}")
    return [
        {"block_id": b.block_id, "block_type": b.block_type}
        for b in (resp.data.items or [])
    ]


def append_text(document_id: str, text: str) -> bool:
    """Append a paragraph to the end of a document."""
    blocks = get_blocks(document_id)
    if not blocks:
        return False
    root_id = blocks[0]["block_id"]
    child = {
        "block_type": 2,
        "paragraph": {"elements": [{"text_run": {"content": text}}]},
    }
    req = (
        BatchUpdateDocumentBlockRequest.builder()
        .document_id(document_id)
        .request_body(
            BatchUpdateDocumentBlockRequestBody.builder()
            .requests(
                [
                    UpdateBlockRequest.builder()
                    .block_id(root_id)
                    .insert_children(
                        InsertChildren.builder().children([child]).index(-1).build()
                    )
                    .build()
                ]
            )
            .build()
        )
        .build()
    )
    resp = _client().docx.v1.document_block.batch_update(req)
    return resp.success()


def replace_doc_content(document_id: str, paragraphs: list[str]) -> bool:
    """Overwrite the document body with *paragraphs* (one string per paragraph).

    Steps:
      1. Fetch current blocks.
      2. Delete all existing content children of the root block.
      3. Create new paragraph blocks.
    """
    blocks = get_blocks(document_id)
    if not blocks:
        return False

    root_id = blocks[0]["block_id"]
    children_count = len(blocks) - 1

    # Delete existing children if any
    if children_count > 0:
        del_req = (
            BatchDeleteDocumentBlockChildrenRequest.builder()
            .document_id(document_id)
            .block_id(root_id)
            .request_body(
                BatchDeleteDocumentBlockChildrenRequestBody.builder()
                .start_index(0)
                .end_index(children_count)
                .build()
            )
            .build()
        )
        _client().docx.v1.document_block_children.batch_delete(del_req)

    if not paragraphs:
        return True

    # Build paragraph Block objects
    children = []
    for p in paragraphs:
        if p.strip():
            children.append(
                Block.builder()
                .block_type(2)
                .text(
                    Text.builder()
                    .elements([
                        TextElement.builder()
                        .text_run(TextRun.builder().content(p).build())
                        .build()
                    ])
                    .build()
                )
                .build()
            )

    if not children:
        return True

    create_req = (
        CreateDocumentBlockChildrenRequest.builder()
        .document_id(document_id)
        .block_id(root_id)
        .request_body(
            CreateDocumentBlockChildrenRequestBody.builder()
            .children(children)
            .index(0)
            .build()
        )
        .build()
    )
    resp = _client().docx.v1.document_block_children.create(create_req)
    return resp.success()


# -- Quick test --

if __name__ == "__main__":
    missing = config.check()
    if missing:
        print(f"Missing env vars: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in credentials.")
    else:
        print("Config OK. Testing connection...")
        try:
            spaces = list_spaces()
            print(f"Found {len(spaces)} wiki space(s):")
            for s in spaces:
                print(f"  - {s['name']} ({s['space_id']})")
        except Exception as e:
            print(f"Error: {e}")
