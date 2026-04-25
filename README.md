# CodeWithCoach Lab

`CodeWithCoach Lab` is a mobile-first practice website for learners who follow coding lessons on a phone.

This is especially useful if your audience comes from `WhatsApp`. You share one link in your WhatsApp channel, group, or status, and followers open the lab in their mobile browser to practice alongside your teaching.

## What it includes

- A `Python Lab` that runs beginner-friendly exercises in the browser
- A `Web Lab` for `HTML`, `CSS`, and `JavaScript`
- Account creation and login
- Cloud-synced coding progress per learner
- Starter challenges your followers can edit
- Automatic local saving with `localStorage`
- A phone-friendly layout
- A share button for sending the lab link again
- Basic install/offline support for repeat visitors

## How to run it

1. Install the database driver:

```bash
pip install -r requirements.txt
```

2. Set your database connection string:

```bash
set DATABASE_URL=postgresql://postgres:123456789@localhost:5432/osartech_hub_db
```

3. Set an invite code that only your followers know:

```bash
set INVITE_CODE=OSARTECH2026
```

4. Bootstrap your Super Admin account:

```bash
set ADMIN_EMAIL=admin@osartechhub.com
set ADMIN_PASSWORD=ChangeThisStrongPassword123
```

5. Start the app server:

```bash
python server.py
```

6. Open `http://127.0.0.1:8000` in your browser.
7. If you want Python execution to work, the browser needs internet access to load the Pyodide runtime from a CDN.

## Backend details

- The backend is a lightweight Python server.
- If `DATABASE_URL` is set to a PostgreSQL URL, the app uses PostgreSQL.
- If `DATABASE_URL` is not set, the app falls back to local `sqlite` in `coachlab.db`.
- If `INVITE_CODE` is set, learners must use that code during registration.
- If `ADMIN_EMAIL` and `ADMIN_PASSWORD` are set, a super admin account is created/updated on startup.
- Login uses secure password hashing and an `HttpOnly` session cookie.
- Sessions are persistent on the device for a long period, so users do not need to log in every time.

## Super Admin features

Once logged in as a super admin, you can:

- View total users, active sessions, and saved-progress rows
- Update invite code without redeploying
- Promote/demote users between `learner` and `super_admin`

## Deploy on Render (recommended)

1. Push this project to GitHub.
2. In Render, click `New` -> `Blueprint` and connect your repo.
3. Render will read [render.yaml](./render.yaml) and create:
- One web service (`osartech-hub-lab`)
- One PostgreSQL database (`osartech-hub-db`)
4. In the web service environment, set `INVITE_CODE` to your current class code.
5. Also set `ADMIN_EMAIL` and `ADMIN_PASSWORD` for your owner account.
6. Deploy and open your new `https://...onrender.com` URL.
7. Test from phone: register with invite code, run an exercise, refresh, confirm login is still active.

If you prefer manual setup instead of blueprint:
- Web service start command: `python server.py`
- Build command: `pip install -r requirements.txt`
- Environment vars: `DATABASE_URL` (from Render Postgres), `INVITE_CODE`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`

## WhatsApp deep links

You can send these links directly to followers:

- `https://your-domain.com/exercise/python-loop` opens the Python Loop lesson
- `https://your-domain.com/exercise/web-quiz` opens the Web Quiz lesson
- `https://your-domain.com/?mode=python&lesson=python-logic` opens a specific lesson by query string
- `https://your-domain.com/?code=OSARTECH2026` prefills the invite code in the register form

## Best way to use it with WhatsApp followers

1. Deploy this site online.
2. Share the website link in your WhatsApp channel, group, or status.
3. Tell followers to open it in their browser and optionally add it to their home screen.
4. Use each lesson during your teaching, then ask them to edit and run the sample code themselves.

## Next ideas

- Add your own channel branding and lesson text
- Add login and teacher dashboards
- Add quizzes and course tracking
