# __NAME__

__EMOJI__ __TAGLINE__

Live at https://__SLUG__.utilbots.com · part of [UtilBots](https://utilbots.com) · built on
[utilbots-core](https://github.com/UnheardOTP/utilbots-core).

## Develop
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
cp .env.example .env   # fill in a Discord app's values
docker compose up -d --build   # site on http://localhost:8080
```

## Deploy
Push to `main`. See utilbots-core `STANDARD.md` for the pipeline, server layout and shared secrets.
