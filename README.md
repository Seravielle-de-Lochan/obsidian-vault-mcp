# Obsidian Vault MCP Server

A small [MCP](https://modelcontextprotocol.io) server, built with [FastMCP](https://github.com/jlowin/fastmcp), that lets an MCP client (Claude Desktop, Claude Code, etc.) read, write, search and organise notes in a local Obsidian vault. It works directly on the Markdown files; Obsidian does not need to be running.

## Tools

| Tool | What it does |
|---|---|
| `list_notes` | List every `.md` note in the vault. |
| `read_note` | Read a note's full contents. |
| `search_notes` | Search note filenames (and optionally contents) by text or regex. |
| `write_note` | Create a note, or overwrite one with `overwrite=True`. |
| `append_to_note` | Append text to a note, optionally with a timestamp. |
| `str_replace_in_note` | Replace every occurrence of an exact string in a note. |
| `get_note_info` | Show size, modified time, word and line counts. |
| `move_note` | Move a note to another folder. |
| `rename_note` | Rename a note within its folder. |
| `delete_note` | Delete a note (requires `confirm=True`). |
| `list_folders` | List all folders in the vault. |
| `create_folder` | Create a folder. |
| `create_daily_note` | Create today's dated note from a frontmatter template. |
| `update_note_frontmatter` | Set `mood`, `tags` or custom frontmatter fields. |
| `add_tags_to_note` | Add tags to a note's frontmatter, keeping existing ones. |
| `get_notes_by_tag` | Find notes with a tag (frontmatter or inline `#tag`). |
| `get_vault_stats` | Totals, top folders, top tags and recorded moods. |
| `get_recent_notes` | List the most recently modified notes. |

Hidden folders (such as `.obsidian`) are skipped. All paths are relative to the vault root, and paths that resolve outside the vault are refused.

## Install

Requires Python 3.10+.

```
pip install -r requirements.txt
```

## Configuration

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `OBSIDIAN_VAULT_PATH` | yes | none | Absolute path to your vault folder. |
| `OBSIDIAN_DAILY_FOLDER` | no | `Journal` | Folder (relative to the vault) for `create_daily_note`. |

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "obsidian": {
      "command": "python",
      "args": ["/absolute/path/to/obsidian-vault-mcp/obsidian_server.py"],
      "env": {
        "OBSIDIAN_VAULT_PATH": "/absolute/path/to/your/vault",
        "OBSIDIAN_DAILY_FOLDER": "Journal"
      }
    }
  }
}
```

On Windows, use paths like `C:\path\to\vault` (escaped backslashes) or forward slashes.

### Claude Code

```
claude mcp add obsidian \
  -e OBSIDIAN_VAULT_PATH=/absolute/path/to/your/vault \
  -e OBSIDIAN_DAILY_FOLDER=Journal \
  -- python /absolute/path/to/obsidian-vault-mcp/obsidian_server.py
```

## Safety

`write_note` (with `overwrite=True`), `str_replace_in_note`, `update_note_frontmatter`, `add_tags_to_note`, `move_note`, `rename_note` and `delete_note` change real files in your vault. Deletes are permanent: files are removed outright, not sent to Obsidian's deleted-files folder or the system recycle bin. Back up your vault, or keep it under version control, before giving an AI client write access.

## License

MIT. See [LICENSE](LICENSE).
