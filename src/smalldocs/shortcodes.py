"Quarto's shortcodes that make sense without Pandoc: `include`, `meta`, `var`, `env`, `pagebreak`, `kbd`, `video`, `lipsum` and `placeholder`."

import base64
import html
import os
import re
import shlex
from pathlib import Path

from .config import read_yaml

SHORTCODE = re.compile(r"(\\?)\{\{<\s*(\w[\w-]*)\s*(.*?)\s*>\}\}")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def lookup(
    data: dict,  # Nested options
    key: str,  # A dotted key, such as `author.name`
) -> object:  # The value, or None
    "Find a dotted key in nested options."
    cur: object = data
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def arguments(
    text: str,  # What follows the shortcode's name, such as `Shift-Ctrl-P mac=Shift-Command-P`
) -> tuple[list[str], dict[str, str]]:  # The plain arguments, and the `key=value` ones
    "Split a shortcode's arguments, with quotes as in a shell."
    try:
        words = shlex.split(text)
    except ValueError:
        words = text.split()
    pos = [w for w in words if not re.match(r"^[\w-]+=", w)]
    kv = dict(w.split("=", 1) for w in words if re.match(r"^[\w-]+=", w))
    return pos, kv


def kbd(
    text: str,  # The arguments: the keys, then `mac=`, `win=` and `linux=` for each system
    count: list[int],  # Not used
) -> str:  # Quarto's markup: a `<kbd>`, and the keys again for screen readers
    "Show keys to press, as Quarto's `kbd` shortcode, with the keys for each system in the title."
    pos, kv = arguments(text)
    systems = {{"win": "windows"}.get(k, k): v for k, v in kv.items() if k in ("mac", "win", "windows", "linux")}
    keys = pos[0] if pos else next(iter(systems.values()), "")
    title = ", ".join([keys, *(f"{s}: {systems[s]}" for s in sorted(systems))])
    data = "".join(f' data-{s}="{html.escape(systems[s])}"' for s in sorted(systems))
    return f'<kbd title="{html.escape(title)}" aria-hidden="true"{data}>{html.escape(keys)}</kbd><span class="visually-hidden">{html.escape(keys)}</span>'


def video(
    text: str,  # The arguments: the address or the file, then `title`, `width`, `height`, `aspect-ratio` and `start`
    count: list[int],  # How many videos the page has so far; this one adds one
) -> str:  # Quarto's markup: an embedded player for YouTube, Vimeo and Brightcove, else a `<video>`
    "Embed a video, as Quarto's `video` shortcode."
    pos, kv = arguments(text)
    src = kv.get("src") or (pos[0] if pos else "")
    title, start = html.escape(kv.get("title", "")), kv.get("start", "")
    size = "".join(f' {k}="{html.escape(kv[k])}"' for k in ("width", "height") if kv.get(k))
    ratio = "" if size else f" ratio ratio-{html.escape(kv.get('aspect-ratio', '16x9'))}"
    yt = re.search(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/)|youtu\.be/)([\w-]+)", src)
    vimeo = re.search(r"vimeo\.com/(?:video/)?(\d+)", src)
    if yt or vimeo or "players.brightcove.net" in src:
        if yt:
            url = f"https://www.youtube.com/embed/{yt.group(1)}" + (f"?start={start}" if start else "")
            allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
        elif vimeo:
            url = f"https://player.vimeo.com/video/{vimeo.group(1)}" + (f"#t={start}s" if start else "")
            allow = "autoplay; fullscreen; picture-in-picture"
        else:
            url, allow = src, "encrypted-media"
        frame = f'<iframe data-external="1" src="{html.escape(url)}"{size} title="{title}" frameborder="0" allow="{allow}" allowfullscreen=""></iframe>'
        return f'<div class="quarto-video{ratio}">{frame}</div>'
    count[0] += 1
    at = f"#t={start}" if start else ""
    return (
        f'<div class="quarto-video"><video id="video_shortcode_videojs_video{count[0]}" class="video-js vjs-default-skin vjs-fluid" controls=""'
        f' preload="auto" data-setup="{{}}"{size} title="{title}"><source src="{html.escape(src + at)}"></video></div>'
    )


def lipsum(
    text: str,  # The arguments: how many paragraphs, such as `2`, or a range, such as `1-3`
    count: list[int],  # Not used
) -> str:  # Paragraphs of placeholder text
    "Write placeholder text, as Quarto's `lipsum` shortcode."
    pos, _ = arguments(text)
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", pos[0]) if pos else None
    first, last = (int(m.group(1)), int(m.group(2) or m.group(1))) if m else (1, 5)
    if m and not m.group(2):
        first, last = 1, int(m.group(1))
    last = min(last, first + 99)  # at most 100 paragraphs
    return "\n\n".join(LIPSUM[(k - 1) % len(LIPSUM)] for k in range(max(1, first), max(1, last) + 1))


def placeholder(
    text: str,  # The arguments: the width, and the height, which is the width when it is missing
    count: list[int],  # Not used
) -> str:  # An `<img>` of a grey box, drawn as SVG in the page
    "Draw a grey box of a given size, as Quarto's `placeholder` shortcode, without a call to a web service."
    pos, _ = arguments(text)
    w = int(pos[0]) if pos and pos[0].isdigit() else 100
    h = int(pos[1]) if len(pos) > 1 and pos[1].isdigit() else w
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="#ced4da"/>'
        f'<text x="50%" y="50%" fill="#6c757d" font-family="sans-serif" font-size="{max(8, min(w, h) // 6)}" text-anchor="middle" dominant-baseline="middle">{w} × {h}</text></svg>'
    )
    return f'<img src="data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}" class="img-fluid" alt="" width="{w}" height="{h}">'


# The shortcodes that make markup, by name: each takes the text of its arguments and the page's count of videos
MADE = {"kbd": kbd, "video": video, "lipsum": lipsum, "placeholder": placeholder}
LIPSUM = [
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Duis sagittis posuere ligula sit amet lacinia. Duis dignissim pellentesque "
    "magna, rhoncus congue sapien finibus mollis. Ut eu sem laoreet, vehicula ipsum in, convallis erat. Vestibulum magna sem, blandit "
    "pulvinar augue sit amet, auctor malesuada sapien. Nullam faucibus leo eget eros hendrerit, non laoreet ipsum lacinia. Curabitur "
    "cursus diam elit, non tempus ante volutpat a. Quisque hendrerit blandit purus non fringilla. Integer sit amet elit viverra ante "
    "dapibus semper. Vestibulum viverra rutrum enim, at luctus enim posuere eu. Orci varius natoque penatibus et magnis dis parturient "
    "montes, nascetur ridiculus mus.",
    "Nunc ac dignissim magna. Vestibulum vitae egestas elit. Proin feugiat leo quis ante condimentum, eu ornare mauris feugiat. "
    "Pellentesque habitant morbi tristique senectus et netus et malesuada fames ac turpis egestas. Mauris cursus laoreet ex, dignissim "
    "bibendum est posuere iaculis. Suspendisse et maximus elit. In fringilla gravida ornare. Aenean id lectus pulvinar, sagittis felis "
    "nec, rutrum risus. Nam vel neque eu arcu blandit fringilla et in quam.",
    "Aliquam luctus est sit amet ante pretium, vel feugiat orci rhoncus. Fusce id neque at magna tempus aliquet. Suspendisse potenti. "
    "Sed sit amet dolor ac velit tincidunt pulvinar. Nam pellentesque, nibh at iaculis iaculis, ante purus congue est, et hendrerit "
    "justo quam a nisi. Cras placerat faucibus ex, et semper erat pellentesque id.",
    "Donec congue ultricies tortor, id fermentum velit dapibus non. Sed et dignissim tellus. Nulla facilisi. Integer fringilla, mi a "
    "finibus maximus, eros odio volutpat mauris, vitae suscipit est enim vel nisi. Proin vitae pretium nibh, a bibendum magna.",
    "Pellentesque tincidunt urna non nisi consequat, sit amet ultrices nibh dignissim. Etiam vitae nulla in nisi lacinia scelerisque "
    "non eu lectus. Maecenas tincidunt neque nec metus fringilla, ut vehicula quam laoreet. Morbi ut lorem ac velit gravida vehicula.",
]


def expand(
    text: str,  # Markdown that may hold shortcodes
    here: Path,  # The file it comes from, for `include` paths
    root: Path,  # The project's root, for `_variables.yml` and paths from `/`
    meta: dict,  # The page's options, for `meta`
    warn: list[str],  # Where to note a shortcode that smalldocs does not know
    depth: int = 0,  # How deep in includes we are, to stop a loop
    count: list[int] | None = None,  # How many videos the page has so far, shared with its includes
) -> str:  # The text with the shortcodes replaced; code blocks are left alone
    "Replace the shortcodes in a page, outside code blocks."
    count = [0] if count is None else count
    if depth > 10:
        warn.append(f"{here}: includes nest more than 10 deep; stopped")
        return text
    variables = {}
    vf = root / "_variables.yml"
    if vf.exists():
        variables = read_yaml(vf) or {}
    out, fence = [], None
    for line in text.split("\n"):
        m = FENCE.match(line)
        if fence:
            out.append(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)) :].strip():
                fence = None
            continue
        if m:
            fence = m.group(1)
            out.append(line)
            continue

        def sub(mm: re.Match) -> str:
            if mm.group(1):
                return mm.group(0)[1:]
            name, arg = mm.group(2), mm.group(3).strip().strip("\"'")
            if name == "include":
                path = (root / arg.lstrip("/")) if arg.startswith("/") else (here.parent / arg)
                if not path.is_file():
                    warn.append(f"{here.name}: include {arg} not found")
                    return ""
                inc = path.read_text(encoding="utf-8-sig")
                inc = re.sub(r"\A---\r?\n.*?\r?\n---\r?\n", "", inc, flags=re.S)
                return expand(inc, path, root, meta, warn, depth + 1, count)
            if name == "meta":
                v = lookup(meta, arg)
                return "" if v is None else str(v)
            if name == "var":
                v = lookup(variables, arg)
                return "" if v is None else str(v)
            if name == "env":
                return os.environ.get(arg, "")
            if name == "pagebreak":
                return ""
            if name in MADE:
                return MADE[name](mm.group(3), count)
            warn.append(f"{here.name}: shortcode {name} is not known to smalldocs; left as it is")
            return mm.group(0)

        out.append(SHORTCODE.sub(sub, line).replace("{{</*", "{{<").replace("*/>}}", ">}}"))
    return "\n".join(out)
