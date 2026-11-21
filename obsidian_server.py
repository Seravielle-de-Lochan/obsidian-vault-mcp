"""
Obsidian Vault MCP Server

Lets an MCP client read, write, search, move, rename, and delete notes in an
Obsidian vault on the local filesystem.

Configuration (environment variables):
    OBSIDIAN_VAULT_PATH    Absolute path to the vault folder (required).
    OBSIDIAN_DAILY_FOLDER  Folder for daily notes, relative to the vault root
                           (optional, default "Journal").
"""

from fastmcp import FastMCP
import os
import re
import shutil
import sys
import yaml
from datetime import datetime
from collections import Counter

# Initialize the MCP server
mcp = FastMCP("Obsidian Vault")

# Path to the Obsidian vault (read from the environment)
VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()

# Daily note settings
DAILY_NOTE_FOLDER = os.environ.get("OBSIDIAN_DAILY_FOLDER", "").strip() or "Journal"
DAILY_NOTE_TEMPLATE = """---
date: {date}
mood:
tags: [journal]
---

# {title}

"""


def vault_error():
    """Return a human-readable explanation of why the vault is unavailable."""
    if not VAULT_PATH:
        return ("Error: OBSIDIAN_VAULT_PATH is not set. Set it to the absolute "
                "path of your Obsidian vault folder.")
    return f"Error: Vault not found at {VAULT_PATH}"


def get_vault_path():
    """Get and validate the vault path."""
    if not VAULT_PATH or not os.path.isdir(VAULT_PATH):
        return None
    return VAULT_PATH


def resolve_in_vault(vault_path, relative_path):
    """Join a relative path onto the vault root, refusing paths that escape it.

    Returns the absolute path, or None if the path would land outside the vault.
    """
    root = os.path.realpath(vault_path)
    full = os.path.realpath(os.path.join(root, relative_path))
    if full != root and not full.startswith(root + os.sep):
        return None
    return full


def get_all_notes(vault_path):
    """Recursively get all markdown files in the vault."""
    notes = []
    for root, dirs, files in os.walk(vault_path):
        # Skip hidden folders and Obsidian config
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            if file.endswith('.md'):
                full_path = os.path.join(root, file)
                relative_path = os.path.relpath(full_path, vault_path)
                notes.append(relative_path)
    return notes


def parse_frontmatter(content):
    """Parse YAML frontmatter from note content. Returns (frontmatter_dict, body)."""
    if not content.startswith('---'):
        return {}, content

    # Find the closing ---
    end_match = re.search(r'\n---\s*\n', content[3:])
    if not end_match:
        return {}, content

    yaml_content = content[3:end_match.start() + 3]
    body = content[end_match.end() + 3:]

    try:
        frontmatter = yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError:
        frontmatter = {}

    if not isinstance(frontmatter, dict):
        frontmatter = {}

    return frontmatter, body


def update_frontmatter(content, updates):
    """Update frontmatter in note content with new values. Returns updated content."""
    frontmatter, body = parse_frontmatter(content)
    frontmatter.update(updates)

    # Rebuild the note
    yaml_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    return f"---\n{yaml_str}---\n{body}"


def extract_tags(content):
    """Extract all tags from a note (both frontmatter and inline #tags)."""
    tags = set()

    # Get frontmatter tags
    frontmatter, body = parse_frontmatter(content)
    if 'tags' in frontmatter:
        fm_tags = frontmatter['tags']
        if isinstance(fm_tags, list):
            tags.update(str(t) for t in fm_tags if t is not None)
        elif isinstance(fm_tags, str):
            tags.add(fm_tags)

    # Get inline tags (e.g., #journal, #ideas)
    inline_tags = re.findall(r'#([a-zA-Z][a-zA-Z0-9_-]*)', body)
    tags.update(inline_tags)

    return tags


# =============================================================================
# BASIC TOOLS
# =============================================================================

@mcp.tool()
def list_notes() -> str:
    """
    List all notes in the Obsidian vault.
    Returns a list of all markdown files with their paths.
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    notes = get_all_notes(vault_path)

    if not notes:
        return "No notes found in the vault."

    return f"Found {len(notes)} notes:\n" + "\n".join(f"  - {note}" for note in sorted(notes))


@mcp.tool()
def read_note(note_path: str) -> str:
    """
    Read the contents of a specific note.

    Args:
        note_path: Path to the note relative to vault root (e.g., "folder/note.md" or just "note.md")
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    # Add .md extension if not present
    if not note_path.endswith('.md'):
        note_path += '.md'

    full_path = resolve_in_vault(vault_path, note_path)
    if not full_path:
        return f"Error: '{note_path}' is outside the vault"

    if not os.path.exists(full_path):
        return f"Error: Note not found at '{note_path}'"

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return f"=== {note_path} ===\n\n{content}"
    except Exception as e:
        return f"Error reading note: {e}"


@mcp.tool()
def search_notes(query: str, search_content: bool = False) -> str:
    """
    Search for notes by filename or content.

    Args:
        query: Search term (case-insensitive, supports regex)
        search_content: If True, also search within note contents (slower)
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    notes = get_all_notes(vault_path)
    matches = []

    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        # If invalid regex, treat as literal string
        pattern = re.compile(re.escape(query), re.IGNORECASE)

    for note in notes:
        # Search filename
        if pattern.search(note):
            matches.append(f"{note} (filename match)")
            continue

        # Search content if requested
        if search_content:
            full_path = os.path.join(vault_path, note)
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                if pattern.search(content):
                    matches.append(f"{note} (content match)")
            except Exception:
                pass

    if not matches:
        return f"No notes found matching '{query}'"

    return f"Found {len(matches)} matching notes:\n" + "\n".join(f"  - {match}" for match in matches)


@mcp.tool()
def write_note(note_path: str, content: str, overwrite: bool = False) -> str:
    """
    Create a new note or overwrite an existing one.

    Args:
        note_path: Path for the note relative to vault root (e.g., "folder/note.md")
        content: The content to write to the note
        overwrite: If True, overwrite existing notes. If False, fail if note exists.
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    # Add .md extension if not present
    if not note_path.endswith('.md'):
        note_path += '.md'

    full_path = resolve_in_vault(vault_path, note_path)
    if not full_path:
        return f"Error: '{note_path}' is outside the vault"

    # Check if note exists
    existed = os.path.exists(full_path)
    if existed and not overwrite:
        return f"Error: Note already exists at '{note_path}'. Set overwrite=True to replace it."

    try:
        # Create directories if needed
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        action = "Updated" if existed else "Created"
        return f"{action} note at '{note_path}'"
    except Exception as e:
        return f"Error writing note: {e}"


@mcp.tool()
def append_to_note(note_path: str, content: str, add_timestamp: bool = False) -> str:
    """
    Append content to the end of an existing note.

    Args:
        note_path: Path to the note relative to vault root
        content: Content to append
        add_timestamp: If True, add a timestamp before the appended content
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    # Add .md extension if not present
    if not note_path.endswith('.md'):
        note_path += '.md'

    full_path = resolve_in_vault(vault_path, note_path)
    if not full_path:
        return f"Error: '{note_path}' is outside the vault"

    if not os.path.exists(full_path):
        return f"Error: Note not found at '{note_path}'. Use write_note to create a new note."

    try:
        with open(full_path, 'a', encoding='utf-8') as f:
            if add_timestamp:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                f.write(f"\n\n---\n*Added {timestamp}*\n\n")
            else:
                f.write("\n\n")
            f.write(content)
        return f"Appended content to '{note_path}'"
    except Exception as e:
        return f"Error appending to note: {e}"


@mcp.tool()
def str_replace_in_note(note_path: str, old_str: str, new_str: str) -> str:
    """
    Replace a string in a note with another string. The old_str must exist in the note.
    Every occurrence is replaced.

    Args:
        note_path: Path to the note relative to vault root
        old_str: The exact string to find and replace
        new_str: The string to replace it with
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    # Add .md extension if not present
    if not note_path.endswith('.md'):
        note_path += '.md'

    full_path = resolve_in_vault(vault_path, note_path)
    if not full_path:
        return f"Error: '{note_path}' is outside the vault"

    if not os.path.exists(full_path):
        return f"Error: Note not found at '{note_path}'"

    if not old_str:
        return "Error: old_str must not be empty"

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check if old_str exists
        if old_str not in content:
            return f"Error: Could not find the specified text in '{note_path}'"

        count = content.count(old_str)
        new_content = content.replace(old_str, new_str)

        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return f"Replaced {count} occurrence(s) in '{note_path}'"
    except Exception as e:
        return f"Error replacing text: {e}"


@mcp.tool()
def get_note_info(note_path: str) -> str:
    """
    Get metadata about a specific note (size, modified date, etc.)

    Args:
        note_path: Path to the note relative to vault root
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    # Add .md extension if not present
    if not note_path.endswith('.md'):
        note_path += '.md'

    full_path = resolve_in_vault(vault_path, note_path)
    if not full_path:
        return f"Error: '{note_path}' is outside the vault"

    if not os.path.exists(full_path):
        return f"Error: Note not found at '{note_path}'"

    try:
        stat = os.stat(full_path)
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        size = stat.st_size

        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
            word_count = len(content.split())
            line_count = len(content.splitlines())

        return (
            f"Note: {note_path}\n"
            f"  Modified: {modified}\n"
            f"  Size: {size} bytes\n"
            f"  Words: {word_count}\n"
            f"  Lines: {line_count}"
        )
    except Exception as e:
        return f"Error getting note info: {e}"


@mcp.tool()
def move_note(note_path: str, new_folder: str) -> str:
    """
    Move a note to a different folder within the vault.

    Args:
        note_path: Current path to the note relative to vault root (e.g., "old_folder/note.md")
        new_folder: Destination folder path (e.g., "Archive" or "Projects/Archive"). Use "" or "." for vault root.
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    # Add .md extension if not present
    if not note_path.endswith('.md'):
        note_path += '.md'

    full_path = resolve_in_vault(vault_path, note_path)
    if not full_path:
        return f"Error: '{note_path}' is outside the vault"

    if not os.path.exists(full_path):
        return f"Error: Note not found at '{note_path}'"

    # Get just the filename
    filename = os.path.basename(note_path)

    # Build new path
    if new_folder in ("", "."):
        new_path = filename
    else:
        new_path = os.path.join(new_folder, filename)

    new_full_path = resolve_in_vault(vault_path, new_path)
    if not new_full_path:
        return f"Error: '{new_path}' is outside the vault"

    # Check if destination already exists
    if os.path.exists(new_full_path):
        return f"Error: A note already exists at '{new_path}'. Rename or delete it first."

    try:
        # Create destination folder if needed
        os.makedirs(os.path.dirname(new_full_path), exist_ok=True)
        shutil.move(full_path, new_full_path)
        return f"Moved '{note_path}' -> '{new_path}'"
    except Exception as e:
        return f"Error moving note: {e}"


@mcp.tool()
def rename_note(note_path: str, new_name: str) -> str:
    """
    Rename a note (keeps it in the same folder).

    Args:
        note_path: Current path to the note relative to vault root (e.g., "folder/old_name.md")
        new_name: New filename (with or without .md extension)
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    # Add .md extension if not present
    if not note_path.endswith('.md'):
        note_path += '.md'
    if not new_name.endswith('.md'):
        new_name += '.md'

    if os.path.basename(new_name) != new_name:
        return "Error: new_name must be a filename, not a path. Use move_note to change folders."

    full_path = resolve_in_vault(vault_path, note_path)
    if not full_path:
        return f"Error: '{note_path}' is outside the vault"

    if not os.path.exists(full_path):
        return f"Error: Note not found at '{note_path}'"

    # Get the folder the note is in
    folder = os.path.dirname(note_path)

    # Build new path (same folder, new name)
    if folder:
        new_path = os.path.join(folder, new_name)
    else:
        new_path = new_name

    new_full_path = os.path.join(os.path.dirname(full_path), new_name)

    # Check if destination already exists
    if os.path.exists(new_full_path):
        return f"Error: A note already exists at '{new_path}'. Choose a different name."

    try:
        shutil.move(full_path, new_full_path)
        return f"Renamed '{note_path}' -> '{new_path}'"
    except Exception as e:
        return f"Error renaming note: {e}"


@mcp.tool()
def delete_note(note_path: str, confirm: bool = False) -> str:
    """
    Delete a note from the vault. This action is permanent!

    Args:
        note_path: Path to the note relative to vault root (e.g., "folder/note.md")
        confirm: Must be set to True to actually delete (safety measure)
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    # Add .md extension if not present
    if not note_path.endswith('.md'):
        note_path += '.md'

    full_path = resolve_in_vault(vault_path, note_path)
    if not full_path:
        return f"Error: '{note_path}' is outside the vault"

    if not os.path.exists(full_path):
        return f"Error: Note not found at '{note_path}'"

    if not confirm:
        return f"Safety check: To delete '{note_path}', call delete_note again with confirm=True. This action is permanent!"

    try:
        os.remove(full_path)
        return f"Deleted '{note_path}'"
    except Exception as e:
        return f"Error deleting note: {e}"


@mcp.tool()
def list_folders() -> str:
    """
    List all folders in the Obsidian vault.
    Useful for seeing where you can move notes to.
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    folders = []
    for root, dirs, files in os.walk(vault_path):
        # Skip hidden folders and Obsidian config
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for d in dirs:
            full_path = os.path.join(root, d)
            relative_path = os.path.relpath(full_path, vault_path)
            folders.append(relative_path)

    if not folders:
        return "No subfolders found in the vault (only the root folder exists)."

    return f"Found {len(folders)} folders:\n" + "\n".join(f"  - {folder}" for folder in sorted(folders))


@mcp.tool()
def create_folder(folder_path: str) -> str:
    """
    Create a new folder in the vault.

    Args:
        folder_path: Path for the new folder relative to vault root (e.g., "Archive" or "Projects/2026")
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    full_path = resolve_in_vault(vault_path, folder_path)
    if not full_path:
        return f"Error: '{folder_path}' is outside the vault"

    if os.path.exists(full_path):
        return f"Folder already exists at '{folder_path}'"

    try:
        os.makedirs(full_path, exist_ok=True)
        return f"Created folder '{folder_path}'"
    except Exception as e:
        return f"Error creating folder: {e}"


# =============================================================================
# ADVANCED TOOLS - Daily notes, tags, and analytics
# =============================================================================

@mcp.tool()
def create_daily_note(content: str = "", mood: str = "", custom_title: str = "") -> str:
    """
    Create a daily journal note with today's date in the daily-note folder
    (OBSIDIAN_DAILY_FOLDER, default "Journal"). Uses a template with frontmatter.

    Args:
        content: Optional content to add to the note body
        mood: Optional mood to set in the frontmatter
        custom_title: Optional custom title (defaults to "Journal - [date]")
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    title = custom_title or f"Journal - {date_str}"
    filename = f"{date_str}.md"
    note_path = os.path.join(DAILY_NOTE_FOLDER, filename)
    full_path = resolve_in_vault(vault_path, note_path)
    if not full_path:
        return f"Error: daily-note folder '{DAILY_NOTE_FOLDER}' is outside the vault"

    # Check if already exists
    if os.path.exists(full_path):
        return f"Daily note already exists at '{note_path}'. Use append_to_note to add content."

    # Create from template
    note_content = DAILY_NOTE_TEMPLATE.format(date=date_str, title=title)

    # Add mood if provided
    if mood:
        note_content = note_content.replace("mood:", f"mood: {mood}", 1)

    # Add content if provided
    if content:
        note_content += content

    try:
        # Create folder if needed
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(note_content)
        return f"Created daily note at '{note_path}'"
    except Exception as e:
        return f"Error creating daily note: {e}"


@mcp.tool()
def update_note_frontmatter(note_path: str, mood: str = None, tags: list = None, custom_fields: dict = None) -> str:
    """
    Update the frontmatter (metadata) of a note. Can set mood, tags, or custom fields.

    Args:
        note_path: Path to the note relative to vault root
        mood: New mood value to set (or None to leave unchanged)
        tags: List of tags to set (replaces existing tags, or None to leave unchanged)
        custom_fields: Dict of custom frontmatter fields to set (e.g., {"rating": 5, "status": "draft"})
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    # Add .md extension if not present
    if not note_path.endswith('.md'):
        note_path += '.md'

    full_path = resolve_in_vault(vault_path, note_path)
    if not full_path:
        return f"Error: '{note_path}' is outside the vault"

    if not os.path.exists(full_path):
        return f"Error: Note not found at '{note_path}'"

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Build updates dict
        updates = {}
        if mood is not None:
            updates['mood'] = mood
        if tags is not None:
            updates['tags'] = tags
        if custom_fields:
            updates.update(custom_fields)

        if not updates:
            return "No updates provided. Specify mood, tags, or custom_fields."

        # Update the frontmatter
        new_content = update_frontmatter(content, updates)

        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        updated_fields = ", ".join(updates.keys())
        return f"Updated frontmatter in '{note_path}': {updated_fields}"

    except Exception as e:
        return f"Error updating frontmatter: {e}"


@mcp.tool()
def add_tags_to_note(note_path: str, new_tags: list) -> str:
    """
    Add tags to a note's frontmatter without removing existing tags.

    Args:
        note_path: Path to the note relative to vault root
        new_tags: List of tags to add (e.g., ["ideas", "evening", "draft"])
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    # Add .md extension if not present
    if not note_path.endswith('.md'):
        note_path += '.md'

    full_path = resolve_in_vault(vault_path, note_path)
    if not full_path:
        return f"Error: '{note_path}' is outside the vault"

    if not os.path.exists(full_path):
        return f"Error: Note not found at '{note_path}'"

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        frontmatter, body = parse_frontmatter(content)

        # Get existing tags (handles missing, empty, string, or list values)
        existing_tags = frontmatter.get('tags') or []
        if isinstance(existing_tags, str):
            existing_tags = [existing_tags]
        elif not isinstance(existing_tags, list):
            existing_tags = [existing_tags]
        if isinstance(new_tags, str):
            new_tags = [new_tags]

        # Merge tags (avoid duplicates, keep original order)
        all_tags = list(existing_tags)
        for t in new_tags:
            if t not in all_tags:
                all_tags.append(t)
        frontmatter['tags'] = all_tags

        # Rebuild content
        yaml_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
        new_content = f"---\n{yaml_str}---\n{body}"

        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return f"Added tags to '{note_path}'. All tags: {all_tags}"

    except Exception as e:
        return f"Error adding tags: {e}"


@mcp.tool()
def get_notes_by_tag(tag: str) -> str:
    """
    Find all notes that have a specific tag (in frontmatter or inline).

    Args:
        tag: The tag to search for (without the # symbol)
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    tag = tag.lstrip('#')
    notes = get_all_notes(vault_path)
    matches = []

    for note in notes:
        full_path = os.path.join(vault_path, note)
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            tags = extract_tags(content)
            if tag.lower() in [t.lower() for t in tags]:
                matches.append(note)
        except Exception:
            pass

    if not matches:
        return f"No notes found with tag '#{tag}'"

    return f"Found {len(matches)} notes with tag '#{tag}':\n" + "\n".join(f"  - {m}" for m in sorted(matches))


@mcp.tool()
def get_vault_stats() -> str:
    """
    Get statistics about the vault: total notes, total words, tags usage, folder breakdown, etc.
    Useful for seeing patterns in your writing.
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    notes = get_all_notes(vault_path)

    if not notes:
        return "Vault is empty - no notes found."

    total_words = 0
    total_lines = 0
    all_tags = Counter()
    folder_counts = Counter()
    moods = Counter()
    oldest_note = None
    newest_note = None
    oldest_date = None
    newest_date = None

    for note in notes:
        full_path = os.path.join(vault_path, note)
        try:
            stat = os.stat(full_path)
            mod_time = datetime.fromtimestamp(stat.st_mtime)

            # Track oldest/newest
            if oldest_date is None or mod_time < oldest_date:
                oldest_date = mod_time
                oldest_note = note
            if newest_date is None or mod_time > newest_date:
                newest_date = mod_time
                newest_note = note

            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Word and line count
            total_words += len(content.split())
            total_lines += len(content.splitlines())

            # Tags
            tags = extract_tags(content)
            all_tags.update(tags)

            # Folder
            folder = os.path.dirname(note) or "(root)"
            folder_counts[folder] += 1

            # Mood from frontmatter
            frontmatter, _ = parse_frontmatter(content)
            if frontmatter.get('mood'):
                moods[str(frontmatter['mood'])] += 1

        except Exception:
            pass

    # Build report
    report = [
        "=== Vault Statistics ===\n",
        f"Total notes: {len(notes)}",
        f"Total words: {total_words:,}",
        f"Total lines: {total_lines:,}",
        f"Average words per note: {total_words // len(notes) if notes else 0}",
        "",
        f"Oldest note: {oldest_note} ({oldest_date.strftime('%Y-%m-%d') if oldest_date else 'N/A'})",
        f"Newest note: {newest_note} ({newest_date.strftime('%Y-%m-%d') if newest_date else 'N/A'})",
    ]

    # Folder breakdown
    report.append("\n--- Notes by Folder ---")
    for folder, count in folder_counts.most_common(10):
        report.append(f"  {folder}: {count}")

    # Top tags
    if all_tags:
        report.append("\n--- Top Tags ---")
        for tag, count in all_tags.most_common(10):
            report.append(f"  #{tag}: {count}")

    # Mood tracking
    if moods:
        report.append("\n--- Moods Recorded ---")
        for mood, count in moods.most_common(10):
            report.append(f"  {mood}: {count}")

    return "\n".join(report)


@mcp.tool()
def get_recent_notes(limit: int = 10) -> str:
    """
    Get the most recently modified notes.

    Args:
        limit: Maximum number of notes to return (default 10)
    """
    vault_path = get_vault_path()
    if not vault_path:
        return vault_error()

    notes = get_all_notes(vault_path)

    # Get modification times
    note_times = []
    for note in notes:
        full_path = os.path.join(vault_path, note)
        try:
            stat = os.stat(full_path)
            mod_time = datetime.fromtimestamp(stat.st_mtime)
            note_times.append((note, mod_time))
        except Exception:
            pass

    # Sort by modification time (newest first)
    note_times.sort(key=lambda x: x[1], reverse=True)

    # Take top N
    recent = note_times[:max(limit, 0)]

    if not recent:
        return "No notes found."

    result = f"Most recent {len(recent)} notes:\n"
    for note, mod_time in recent:
        result += f"  - {note} ({mod_time.strftime('%Y-%m-%d %H:%M')})\n"

    return result


if __name__ == "__main__":
    if not VAULT_PATH:
        sys.exit("OBSIDIAN_VAULT_PATH is not set. Set it to the absolute path of your Obsidian vault.")
    if not os.path.isdir(VAULT_PATH):
        sys.exit(f"OBSIDIAN_VAULT_PATH does not point to a folder: {VAULT_PATH}")
    mcp.run()
