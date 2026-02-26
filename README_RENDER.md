## Deploy to Render (this project)

### Render settings
- **Build command**:
  - `pip install -r requirements.in`
  - `python manage.py collectstatic --noinput`
  - `python manage.py migrate`
- **Start command**:
  - `gunicorn medtracker.wsgi:application`

### Python version
Render is currently defaulting to Python 3.14.x for your service. Set one of:
- Render dashboard → **Environment** → add `PYTHON_VERSION=3.11.9`
- or Render dashboard → **Settings** → choose Python `3.11.x` (if available)

### Environment variables
- `GROQ_API_KEY`: required for the dashboard chatbot.

