# twitter_del

Daily manager for **your own** X (Twitter) account.

It uses the official X API only. It does not scrape x.com and it does not ask for your password.

Each run can:

1. Delete up to **100 of your own posts** (oldest first)
2. Publish up to **10 posts** that include your keyword

Default keyword drafts are about fly connectome, Solana, theory, and cosmic ideas. Change them anytime.

## Requirements

- Python 3.10+
- An X developer app with **Read and Write**
- Paid X API credits (posting and deleting are billed per request in 2026)
- OAuth 1.0a user tokens for the account you want to manage

X Premium (blue check) is not the same thing as API access.

## Setup

```bash
git clone https://github.com/atongsa/twitter_del.git
cd twitter_del
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```
X_API_KEY=...
X_API_SECRET=...
X_ACCESS_TOKEN=...
X_ACCESS_TOKEN_SECRET=...
POST_KEYWORD=fly connectome
DELETE_PER_DAY=100
POST_PER_DAY=10
```

Get those four keys from [developer.x.com](https://developer.x.com) / [console.x.com](https://console.x.com). Never commit `.env`.

Optional: edit `post_templates.txt`. One post per line. `{keyword}` is replaced by `POST_KEYWORD` or `--keyword`.

## Usage

Always dry-run first:

```bash
python x_daily_manager.py --dry-run --keyword "fly connectome"
```

Real run:

```bash
python x_daily_manager.py --keyword "fly connectome"
```

Useful flags:

| Flag | What it does |
|---|---|
| `--keyword "..."` | Keyword for today's posts (overrides `.env`) |
| `--delete-count 100` | Max deletes this run (capped at 100) |
| `--post-count 10` | Max new posts this run (capped at 10) |
| `--delete-only` | Only delete, do not post |
| `--post-only` | Only post, do not delete |
| `--from-archive tweet.js` | Delete older posts using your official X archive |
| `--dry-run` | Print actions, change nothing |
| `--verbose` | Extra log detail |

The live API only sees about the last 3,200 posts. For older history, download your archive from X:

**Settings → Your account → Download an archive of your data**

Then:

```bash
python x_daily_manager.py --from-archive /path/to/tweet.js --keyword "fly connectome"
```

## Schedule once a day

Cron example at 09:00:

```bash
0 9 * * * cd /path/to/twitter_del && .venv/bin/python x_daily_manager.py --keyword "fly connectome" >> x_daily_manager.log 2>&1
```

The script remembers today's counts in `state.json` so a second run the same day will not delete or post extra items.

## Cost and safety

Approximate official pay-per-use rates (check current X pricing before you buy credits):

- Delete one post: about $0.010
- Create one text post: about $0.015
- Create a post that contains a URL: about $0.20

100 deletes + 10 text posts is roughly **$1–2 per day**, plus a little to list your own posts.

100 deletes/day is a cautious pace. It lowers lock risk. It does not make a ban impossible.

This tool only acts on the account that authorized the tokens. It cannot delete anyone else's posts.

When you are done, revoke the app:

**X → Settings → Security and account access → Apps and sessions → Connected apps**

## License

Dual-licensed. You may use this project under **either**:

- the MIT License (`LICENSE-MIT`)
- the GNU General Public License v3.0 or later (`LICENSE-GPL-3.0`)

See `LICENSE` for the short notice.
