# Bayou Bombers Throws App V2

A self-hosted Python/Flask web app for Bayou Bombers throws training operations.

This implementation follows the provided workflow and UI instruction PDFs, with a Python backend and HTML/CSS/JavaScript frontend.

## Features Implemented

### Authentication and Security
- Role-based login (`coach`, `athlete`)
- Public registration flow for new users (email, name, password, role)
- Passwords are **hashed** with Werkzeug (`generate_password_hash`) and never stored in plaintext
- CSRF protection on all form POST actions
- Server-side authorization checks on every protected route
- Input length limits and basic validation for form data

### Coach Capabilities
- Coach dashboard with:
  - Event-group cards (Shotput / Discus / Javelin)
  - Live practice dashboard
  - Practice completion tracking
- Generate shareable 8-character coach code for athlete roster linking
- Create athlete profiles + athlete login accounts
- Create reusable modules (variation, reps, measured flag, cues, info, demo URL)
- Build and assign daily practice plans from module library
- Add coach notes
- View weekly reports (best/worst mark, completion %, meet highlights, notes)
- Approve projected lift max increases

### Athlete Capabilities
- Register as athlete and optionally link to a coach with coach code
- View today’s assigned practice
- Expand module details and submit module results
- Mark completion for each module
- Submit throw marks (low/typical/best)
- Submit lift entries with burnout-based projected max increase suggestion
- Submit meet performance entries
- View recent meet and lift history

### Data and Reporting
- SQLite-backed persistence
- Models/tables for users, athletes, modules, plans, assignments, results, lifts, meets, and notes
- Weekly aggregation report for coach review
- Live coach dashboard polling endpoint (`/api/live-status`)

### UI and Styling
- Team-branded dark/metal-style UI
- Reusable button/module/event card components
- Mobile-friendly responsive behavior
- Uses provided visual assets in `static/images`

---

## Project Structure

```
BayouBombersAppV2/
  app.py
  config.py
  requirements.txt
  data/
    bayou_bombers.db (created at runtime)
  templates/
    base.html
    login.html
    coach_home.html
    athlete_home.html
    create_practice.html
    modules.html
    athletes.html
    reports.html
    error.html
  static/
    css/
      styles.css
    js/
      app.js
      practice-builder.js
      modules.js
    images/
      bayou-bombers-logo.png
      metal-bg.jpg
      calendar-icon.svg
      default-athlete-avatar.svg
```

---

## Configuration (`config.py`)

`config.py` includes runtime config options, including requested host/port defaults:

- `HOST` (default `0.0.0.0`)
- `PORT` (default `8000`)
- `DEBUG` (default `false`)
- `SECRET_KEY`
- `DATABASE_PATH`
- `POLL_SECONDS`
- `MAX_FORM_TEXT`
- `ADMIN_DEFAULT_USERNAME`
- `ADMIN_DEFAULT_PASSWORD`
- `ATHLETE_DEFAULT_PASSWORD`
- `ENFORCE_DEFAULT_PASSWORD_CHANGE`

Environment variable overrides:

- `BAYOU_HOST`
- `BAYOU_PORT`
- `BAYOU_DEBUG`
- `BAYOU_SECRET_KEY`
- `BAYOU_DATABASE_PATH`
- `BAYOU_POLL_SECONDS`
- `BAYOU_MAX_FORM_TEXT`
- `BAYOU_ADMIN_USERNAME`
- `BAYOU_ADMIN_PASSWORD`
- `BAYOU_ATHLETE_PASSWORD`
- `BAYOU_ENFORCE_PASSWORD_CHANGE`

> **Important:** Set a strong `BAYOU_SECRET_KEY` and `BAYOU_ADMIN_PASSWORD` in production.

---

## Setup

1. Create/activate a Python virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run app:

```bash
python app.py
```

4. Open browser:

```text
http://localhost:8000
```

App bootstraps DB/tables automatically and seeds starter data.  
On first run, if no coach exists and `BAYOU_ADMIN_USERNAME`/`BAYOU_ADMIN_PASSWORD` are not set,
the app prompts in the console for initial admin username/password.

---

## Login and Registration

### Coach
- First run: create coach admin credentials in console prompt, or set:
  - `BAYOU_ADMIN_USERNAME`
  - `BAYOU_ADMIN_PASSWORD`
- Additional coach accounts can be created through the Register page.

### Athlete (examples)
- Username: `averyjames`
- Username: `masonhall`
- Username: `liamross`
- Password for seeded athletes: `athlete123!`

Use the home page **Register** option for new user accounts.
Athletes can enter a coach code during registration or later from athlete account settings.

---

## Security Notes

- Passwords are stored as hashes only.
- CSRF token enforced for all form submissions.
- Route-level role checks prevent unauthorized access.
- Server-side checks verify athlete ownership of submitted practice data.
- Session cookie security flags are configured in `config.py`.

---

## Questions / Issues for Next Agent Session

1. **Password reset/account management UI is not yet implemented.**
   - Add coach-managed password reset and optional athlete self-service reset workflow.

2. **No fine-grained RBAC beyond coach/athlete.**
   - Guardian and assistant-coach roles are noted in scope but not implemented.

3. **Detailed throw-by-throw session analytics are basic.**
   - Add full detailed throw logging UI and trend calculations for prolonged underperformance rules.

4. **PR baseline editing UX is minimal.**
   - Add coach UI to edit athlete PR baselines per event/implement/throw type.

5. **No automated test suite yet.**
   - Add unit/integration tests for auth, CSRF, assignment permissions, and report calculations.

6. **No migrations framework yet.**
   - Consider Alembic-style migration system for schema evolution.

7. **Asset completeness.**
   - PDFs reference more optional image assets (rivet overlays, avatar packs) not fully provided; app currently uses available source assets and generated SVG fallbacks.

8. **Live dashboard currently polls on interval only.**
   - Consider WebSocket/SSE for lower-latency updates.

---

## License / Usage

Internal project implementation for Bayou Bombers app planning and development.
