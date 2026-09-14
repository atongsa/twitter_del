#!/usr/bin/env python3
"""
Daily X (Twitter) manager — official API only.

Default plan:
  - delete up to 100 of YOUR own posts per day (oldest first)
  - publish up to 10 posts per day that include your keyword

This does not scrape x.com and does not use your password.
You must create a developer app and use OAuth 1.0a user tokens.

X paid API access is required for posting and deleting in 2026.
Free/unauthenticated scraping will get the account locked. Do not add it.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import tweepy
except ImportError:
    print("Install dependencies first: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)


BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "state.json"
TEMPLATES_PATH = BASE_DIR / "post_templates.txt"
LOG_PATH = BASE_DIR / "x_daily_manager.log"

# Conservative defaults. X still rate-limits deletes; going much faster
# is what usually trips automated-behavior flags.
DEFAULT_DELETE_PER_DAY = 100
DEFAULT_POST_PER_DAY = 10
DELETE_PAUSE_SECONDS = 8.0
POST_PAUSE_SECONDS = 12.0
PAGE_SIZE = 100


def load_env_file(path: Path) -> None:
    """Minimal .env loader so the script runs without extra packages."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def setup_logging(verbose: bool) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    handlers.append(logging.FileHandler(LOG_PATH, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("REPLACE_"):
        raise SystemExit(
            f"Missing {name}. Copy .env.example to .env and fill in your X API keys."
        )
    return value


def make_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=require_env("X_API_KEY"),
        consumer_secret=require_env("X_API_SECRET"),
        access_token=require_env("X_ACCESS_TOKEN"),
        access_token_secret=require_env("X_ACCESS_TOKEN_SECRET"),
        wait_on_rate_limit=True,
    )


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {
            "deleted_ids": [],
            "posted_texts": [],
            "days": {},
        }
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def today_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def day_bucket(state: dict) -> dict:
    key = today_key()
    days = state.setdefault("days", {})
    if key not in days:
        days[key] = {"deleted": 0, "posted": 0, "posted_texts": []}
    return days[key]


def load_templates(keyword: str) -> list[str]:
    if not TEMPLATES_PATH.exists():
        raise SystemExit(
            f"Missing {TEMPLATES_PATH.name}. Add one post idea per line."
        )
    lines = []
    for raw in TEMPLATES_PATH.read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        if "{keyword}" in text:
            text = text.replace("{keyword}", keyword)
        elif keyword.lower() not in text.lower():
            text = f"{text} {keyword}"
        if len(text) > 280:
            logging.warning("Skipping template over 280 characters: %s", text[:60])
            continue
        lines.append(text)
    if not lines:
        raise SystemExit("post_templates.txt has no usable lines.")
    return lines


def get_me(client: tweepy.Client) -> tweepy.User:
    me = client.get_me(user_auth=True)
    if not me or not me.data:
        raise SystemExit("Could not read the authenticated user. Check your access tokens.")
    return me.data


def fetch_own_posts(client: tweepy.Client, user_id: str, already_deleted: set[str]) -> list[dict]:
    """Return own posts, oldest first, skipping IDs already deleted by this script."""
    posts: list[dict] = []
    pagination_token = None
    # Live user-timeline endpoint only reaches recent history (~3,200).
    # For older posts, import IDs from your official X archive (see --from-archive).
    while True:
        resp = client.get_users_tweets(
            id=user_id,
            max_results=PAGE_SIZE,
            tweet_fields=["created_at", "text"],
            exclude=["retweets"],
            pagination_token=pagination_token,
            user_auth=True,
        )
        if resp.data:
            for tweet in resp.data:
                tweet_id = str(tweet.id)
                if tweet_id in already_deleted:
                    continue
                posts.append(
                    {
                        "id": tweet_id,
                        "text": tweet.text,
                        "created_at": tweet.created_at.isoformat() if tweet.created_at else "",
                    }
                )
        meta = resp.meta or {}
        pagination_token = meta.get("next_token")
        if not pagination_token:
            break
        time.sleep(1)
    posts.sort(key=lambda item: item["created_at"] or "")
    return posts


def load_archive_ids(archive_path: Path) -> list[str]:
    """Read tweet IDs from X archive tweet.js / tweets.js / a plain ID list."""
    raw = archive_path.read_text(encoding="utf-8")
    if raw.lstrip().startswith("window.") or raw.lstrip().startswith("["):
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            raise SystemExit("Could not parse archive JSON array.")
        data = json.loads(raw[start : end + 1])
        ids = []
        for item in data:
            tweet = item.get("tweet", item)
            tweet_id = str(tweet.get("id_str") or tweet.get("id") or "")
            if tweet_id:
                ids.append(tweet_id)
        # Oldest first when the archive includes timestamps.
        def created(item) -> str:
            tweet = item.get("tweet", item) if isinstance(item, dict) else {}
            return tweet.get("created_at", "")
        try:
            data_sorted = sorted(data, key=created)
            ids = [
                str(item.get("tweet", item).get("id_str") or item.get("tweet", item).get("id"))
                for item in data_sorted
                if str(item.get("tweet", item).get("id_str") or item.get("tweet", item).get("id"))
            ]
        except Exception:
            pass
        return ids
    return [line.strip() for line in raw.splitlines() if line.strip() and line.strip().isdigit()]


def delete_posts(
    client: tweepy.Client,
    posts: list[dict],
    limit: int,
    dry_run: bool,
    state: dict,
) -> int:
    bucket = day_bucket(state)
    remaining = max(0, limit - bucket["deleted"])
    if remaining == 0:
        logging.info("Already deleted %s posts today. Skipping deletes.", bucket["deleted"])
        return 0

    deleted = 0
    deleted_ids = set(state.get("deleted_ids", []))
    for post in posts:
        if deleted >= remaining:
            break
        tweet_id = post["id"]
        preview = (post.get("text") or "")[:80].replace("\n", " ")
        if dry_run:
            logging.info("[dry-run] would delete %s | %s", tweet_id, preview)
            deleted += 1
            continue
        try:
            client.delete_tweet(tweet_id, user_auth=True)
            deleted_ids.add(tweet_id)
            deleted += 1
            bucket["deleted"] += 1
            logging.info("Deleted %s | %s", tweet_id, preview)
        except tweepy.Forbidden as exc:
            logging.error("Forbidden deleting %s: %s", tweet_id, exc)
            break
        except tweepy.NotFound:
            deleted_ids.add(tweet_id)
            logging.info("Already gone: %s", tweet_id)
        except tweepy.TooManyRequests:
            logging.warning("Hit delete rate limit. Stopping deletes for this run.")
            break
        except tweepy.TweepyException as exc:
            logging.error("Failed deleting %s: %s", tweet_id, exc)
            time.sleep(20)
            continue
        time.sleep(DELETE_PAUSE_SECONDS)
    state["deleted_ids"] = list(deleted_ids)[-5000:]
    return deleted


def publish_posts(
    client: tweepy.Client,
    templates: list[str],
    limit: int,
    dry_run: bool,
    state: dict,
) -> int:
    bucket = day_bucket(state)
    remaining = max(0, limit - bucket["posted"])
    if remaining == 0:
        logging.info("Already published %s posts today. Skipping posts.", bucket["posted"])
        return 0

    used = set(state.get("posted_texts", [])) | set(bucket.get("posted_texts", []))
    pool = [text for text in templates if text not in used] or list(templates)
    random.shuffle(pool)

    published = 0
    for text in pool:
        if published >= remaining:
            break
        if dry_run:
            logging.info("[dry-run] would post: %s", text)
            published += 1
            continue
        try:
            resp = client.create_tweet(text=text, user_auth=True)
            tweet_id = resp.data["id"] if resp and resp.data else "unknown"
            published += 1
            bucket["posted"] += 1
            bucket.setdefault("posted_texts", []).append(text)
            state.setdefault("posted_texts", []).append(text)
            logging.info("Posted %s | %s", tweet_id, text)
        except tweepy.Forbidden as exc:
            logging.error("Forbidden posting. Check app write permissions: %s", exc)
            break
        except tweepy.TooManyRequests:
            logging.warning("Hit post rate limit. Stopping posts for this run.")
            break
        except tweepy.TweepyException as exc:
            logging.error("Failed posting: %s", exc)
            time.sleep(20)
            continue
        time.sleep(POST_PAUSE_SECONDS)
    state["posted_texts"] = state.get("posted_texts", [])[-500:]
    return published


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete 100 of your X posts and publish 10 keyword posts per day.")
    parser.add_argument("--keyword", default=os.getenv("POST_KEYWORD", ""), help="Keyword appended to each daily post")
    parser.add_argument("--delete-count", type=int, default=int(os.getenv("DELETE_PER_DAY", DEFAULT_DELETE_PER_DAY)))
    parser.add_argument("--post-count", type=int, default=int(os.getenv("POST_PER_DAY", DEFAULT_POST_PER_DAY)))
    parser.add_argument("--from-archive", type=Path, help="Optional path to tweet.js from your X data archive")
    parser.add_argument("--delete-only", action="store_true")
    parser.add_argument("--post-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without calling X")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    load_env_file(BASE_DIR / ".env")
    args = parse_args()
    setup_logging(args.verbose)

    if args.delete_count < 0 or args.post_count < 0:
        raise SystemExit("Counts must be >= 0")
    if args.delete_count > 100:
        logging.warning("Capping deletes at 100/day. Raise this only if you accept more lock risk.")
        args.delete_count = 100
    if args.post_count > 10:
        logging.warning("Capping posts at 10/day.")
        args.post_count = 10

    keyword = (args.keyword or os.getenv("POST_KEYWORD", "")).strip()
    if not args.delete_only and not keyword:
        raise SystemExit("Set --keyword or POST_KEYWORD in .env")

    client = make_client()
    me = get_me(client)
    logging.info("Authenticated as @%s (%s)", me.username, me.id)

    state = load_state()
    deleted = 0
    posted = 0

    if not args.post_only:
        if args.from_archive:
            archive_ids = load_archive_ids(args.from_archive)
            already = set(state.get("deleted_ids", []))
            posts = [{"id": tweet_id, "text": "", "created_at": ""} for tweet_id in archive_ids if tweet_id not in already]
            logging.info("Loaded %s remaining IDs from archive", len(posts))
        else:
            posts = fetch_own_posts(client, str(me.id), set(state.get("deleted_ids", [])))
            logging.info("Found %s of your posts in the live API window", len(posts))
        deleted = delete_posts(client, posts, args.delete_count, args.dry_run, state)

    if not args.delete_only:
        templates = load_templates(keyword)
        posted = publish_posts(client, templates, args.post_count, args.dry_run, state)

    save_state(state)
    logging.info(
        "Done. deleted=%s posted=%s dry_run=%s today=%s",
        deleted,
        posted,
        args.dry_run,
        today_key(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
