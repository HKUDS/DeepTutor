#!/usr/bin/env python3
"""
Generate Stargazers and Forkers roster SVG images for GitHub README.
Modern, minimal style - shows latest users with "and X others" text.

Usage:
    python generate_roster.py --repo HKUDS/DeepTutor --output assets/roster
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import ssl
import urllib.request

# Create SSL context that doesn't verify certificates (for macOS compatibility)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


def fetch_repo_stats(owner: str, repo: str, token: str = None) -> dict:
    """Fetch repository statistics (accurate counts) from GitHub API."""
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "Repo-Roster-Generator"}
    if token:
        headers["Authorization"] = f"token {token}"

    url = f"https://api.github.com/repos/{owner}/{repo}"
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
            data = json.loads(response.read().decode())
            return {
                "stargazers_count": data.get("stargazers_count", 0),
                "forks_count": data.get("forks_count", 0),
            }
    except Exception as e:
        print(f"Error fetching repo stats: {e}")
        return {"stargazers_count": 0, "forks_count": 0}


def fetch_github_api(url: str, token: str = None, count_only: bool = False) -> tuple:
    """Fetch data from GitHub API with pagination. Returns (users, total_count)."""
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "Repo-Roster-Generator"}
    if token:
        headers["Authorization"] = f"token {token}"

    all_data = []
    page = 1
    per_page = 100
    total_count = 0

    while True:
        paginated_url = f"{url}?per_page={per_page}&page={page}"
        req = urllib.request.Request(paginated_url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
                data = json.loads(response.read().decode())
                if not data:
                    break
                all_data.extend(data)
                total_count += len(data)
                if len(data) < per_page:
                    break
                page += 1
                # Keep counting but limit data collection
                if len(all_data) >= 500:
                    # Continue counting total
                    while True:
                        page += 1
                        paginated_url = f"{url}?per_page={per_page}&page={page}"
                        req = urllib.request.Request(paginated_url, headers=headers)
                        try:
                            with urllib.request.urlopen(
                                req, timeout=30, context=ssl_context
                            ) as resp:
                                more_data = json.loads(resp.read().decode())
                                if not more_data:
                                    break
                                total_count += len(more_data)
                                if len(more_data) < per_page:
                                    break
                        except Exception:
                            break
                    break
        except Exception as e:
            print(f"Error fetching {paginated_url}: {e}")
            break

    return all_data, total_count


def fetch_avatar_as_base64(avatar_url: str, size: int = 48) -> str:
    """Fetch avatar image and convert to base64 data URI."""
    try:
        if "?" in avatar_url:
            avatar_url += f"&s={size}"
        else:
            avatar_url += f"?s={size}"

        req = urllib.request.Request(avatar_url, headers={"User-Agent": "Repo-Roster-Generator"})
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
            data = response.read()
            content_type = response.headers.get("Content-Type", "image/png")
            base64_data = base64.b64encode(data).decode("utf-8")
            return f"data:{content_type};base64,{base64_data}"
    except Exception as e:
        print(f"Error fetching avatar {avatar_url}: {e}")
        return None


def generate_modern_roster_svg(
    users: list,
    total_count: int,
    title: str,
    theme: str = "dark",
    display_count: int = 6,
    avatar_size: int = 36,
) -> str:
    """Generate modern minimal SVG with overlapping avatars."""

    # Get latest users (reverse to show newest first)
    display_users = (
        list(reversed(users[-display_count:]))
        if len(users) >= display_count
        else list(reversed(users))
    )
    others_count = total_count - len(display_users)

    if not display_users:
        return generate_empty_svg(title, theme)

    # Theme colors
    if theme == "dark":
        bg_color = "#0d1117"
        text_color = "#e6edf3"
        muted_color = "#8b949e"
        border_color = "#30363d"
        accent_color = "#58a6ff"
    else:
        bg_color = "#ffffff"
        text_color = "#1f2328"
        muted_color = "#656d76"
        border_color = "#d0d7de"
        accent_color = "#0969da"

    # Calculate dimensions
    overlap = 12  # How much avatars overlap
    avatar_spacing = avatar_size - overlap
    avatars_width = avatar_size + (len(display_users) - 1) * avatar_spacing

    padding_x = 24
    padding_y = 16

    # Text measurements (approximate)
    title_width = len(title) * 9
    others_text = f"and {others_count:,} others" if others_count > 0 else ""
    others_width = len(others_text) * 7 if others_text else 0

    total_content_width = avatars_width + 16 + others_width
    width = max(total_content_width + padding_x * 2, 280)
    height = avatar_size + padding_y * 2 + 28  # Extra space for title

    # Fetch avatars
    print(f"Fetching {len(display_users)} avatars for {title}...")
    avatar_cache = {}

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_user = {
            executor.submit(fetch_avatar_as_base64, user["avatar_url"], avatar_size * 2): user[
                "login"
            ]
            for user in display_users
        }
        for future in as_completed(future_to_user):
            login = future_to_user[future]
            try:
                avatar_cache[login] = future.result()
            except Exception as e:
                print(f"Error processing {login}: {e}")

    # Build SVG
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs>",
        "<style>",
        '@import url("https://fonts.googleapis.com/css2?family=Inter:wght@500;600&amp;display=swap");',
        '.title { font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-weight: 600; }',
        '.others { font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-weight: 500; }',
        "</style>",
        "</defs>",
        f'<rect width="100%" height="100%" fill="{bg_color}" rx="12"/>',
    ]

    # Title
    svg_parts.append(
        f'<text x="{padding_x}" y="{padding_y + 14}" class="title" fill="{text_color}" font-size="14">{title}</text>'
    )

    # Avatars row
    avatar_y = padding_y + 28

    for i, user in enumerate(display_users):
        x = padding_x + i * avatar_spacing
        avatar_data = avatar_cache.get(user["login"])

        clip_id = f"clip-{i}"
        svg_parts.append(
            f'<clipPath id="{clip_id}"><circle cx="{x + avatar_size / 2}" cy="{avatar_y + avatar_size / 2}" r="{avatar_size / 2}"/></clipPath>'
        )

        # White/dark border ring for depth
        svg_parts.append(
            f'<circle cx="{x + avatar_size / 2}" cy="{avatar_y + avatar_size / 2}" r="{avatar_size / 2 + 2}" fill="{bg_color}"/>'
        )

        if avatar_data:
            svg_parts.append(
                f'<image x="{x}" y="{avatar_y}" width="{avatar_size}" height="{avatar_size}" '
                f'clip-path="url(#{clip_id})" xlink:href="{avatar_data}" preserveAspectRatio="xMidYMid slice"/>'
            )
        else:
            svg_parts.append(
                f'<circle cx="{x + avatar_size / 2}" cy="{avatar_y + avatar_size / 2}" r="{avatar_size / 2}" fill="{border_color}"/>'
            )
            svg_parts.append(
                f'<text x="{x + avatar_size / 2}" y="{avatar_y + avatar_size / 2 + 5}" text-anchor="middle" '
                f'fill="{text_color}" font-size="14" font-weight="600">{user["login"][0].upper()}</text>'
            )

    # "and X others" text
    if others_count > 0:
        text_x = padding_x + avatars_width + 12
        text_y = avatar_y + avatar_size / 2 + 5
        svg_parts.append(
            f'<text x="{text_x}" y="{text_y}" class="others" fill="{muted_color}" font-size="13">and {others_count:,} others</text>'
        )

    svg_parts.append("</svg>")

    return "\n".join(svg_parts)


def generate_empty_svg(title: str, theme: str) -> str:
    """Generate empty state SVG."""
    if theme == "dark":
        bg_color = "#0d1117"
        text_color = "#8b949e"
    else:
        bg_color = "#ffffff"
        text_color = "#656d76"

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="60">
<rect width="100%" height="100%" fill="{bg_color}" rx="12"/>
<text x="100" y="35" text-anchor="middle" fill="{text_color}"
font-family="Inter, -apple-system, sans-serif" font-size="13" font-weight="500">
No {title.lower()} yet
</text>
</svg>'''


def main():
    parser = argparse.ArgumentParser(description="Generate GitHub roster SVG images")
    parser.add_argument("--repo", required=True, help="GitHub repo in format owner/repo")
    parser.add_argument("--output", default="assets/roster", help="Output directory")
    parser.add_argument("--theme", default="dark", choices=["dark", "light"], help="Color theme")
    parser.add_argument("--display", type=int, default=6, help="Number of avatars to display")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"), help="GitHub token")

    args = parser.parse_args()

    owner, repo = args.repo.split("/")

    # Create output directory
    os.makedirs(args.output, exist_ok=True)

    # Fetch accurate counts from repo API
    print(f"Fetching repo stats for {args.repo}...")
    repo_stats = fetch_repo_stats(owner, repo, args.token)
    stargazers_total = repo_stats["stargazers_count"]
    forks_total = repo_stats["forks_count"]
    print(f"Repo stats: {stargazers_total:,} stars, {forks_total:,} forks")

    # Fetch stargazers (only need latest ones for avatars)
    print(f"Fetching stargazers for {args.repo}...")
    stargazers_url = f"https://api.github.com/repos/{owner}/{repo}/stargazers"
    stargazers, _ = fetch_github_api(stargazers_url, args.token)
    print(f"Fetched {len(stargazers)} stargazer records for avatars")

    # Fetch forkers (only need latest ones for avatars)
    print(f"Fetching forkers for {args.repo}...")
    forks_url = f"https://api.github.com/repos/{owner}/{repo}/forks"
    forks, _ = fetch_github_api(forks_url, args.token)
    forkers = [
        {"login": f["owner"]["login"], "avatar_url": f["owner"]["avatar_url"]} for f in forks
    ]
    print(f"Fetched {len(forkers)} forker records for avatars")

    # Generate stargazers SVG
    print("Generating stargazers SVG...")
    stargazers_svg = generate_modern_roster_svg(
        stargazers, stargazers_total, "Stargazers", theme=args.theme, display_count=args.display
    )
    stargazers_path = os.path.join(args.output, "stargazers.svg")
    with open(stargazers_path, "w", encoding="utf-8") as f:
        f.write(stargazers_svg)
    print(f"Saved: {stargazers_path}")

    # Generate forkers SVG
    print("Generating forkers SVG...")
    forkers_svg = generate_modern_roster_svg(
        forkers, forks_total, "Forkers", theme=args.theme, display_count=args.display
    )
    forkers_path = os.path.join(args.output, "forkers.svg")
    with open(forkers_path, "w", encoding="utf-8") as f:
        f.write(forkers_svg)
    print(f"Saved: {forkers_path}")

    print("Done!")


if __name__ == "__main__":
    main()
