# Deployment Guide

## Overview

The agent_builder Django app runs within the IOLabs project on z2, served by gunicorn behind nginx.

## Infrastructure

| Component           | Detail                                                      |
| ------------------- | ----------------------------------------------------------- |
| **Public URL**      | https://zara2stra.duckdns.org/agent-builder/                |
| **Server**          | z2 (Arch Linux)                                             |
| **Port**            | 8045 (gunicorn), 443 (nginx proxy)                          |
| **Python venv**     | `/home/chris/.pyenv/versions/iolabs/`                       |
| **Systemd service** | `django-iolabs` (user-level)                                |
| **Django app repo** | `/storage/Projects/webapps/IOLabs/AI/django-agent_builder/` |
| **IOLabs project**  | `/storage/Projects/webapps/IOLabs/iolabs/iolabs/`           |
| **nginx config**    | `/etc/nginx/sites-available/z2.conf`                        |
| **Static files**    | `/storage/Projects/webapps/IOLabs/iolabs/iolabs/static/`    |

## Deploy Steps

After completing tasks that change models, static files, or URLs:

```bash
# 1. Install the app (editable mode)
cd /storage/Projects/webapps/IOLabs/AI/django-agent_builder
/home/chris/.pyenv/versions/iolabs/bin/pip install -e .

# 2. Run migrations
cd /storage/Projects/webapps/IOLabs/iolabs/iolabs
/home/chris/.pyenv/versions/iolabs/bin/python manage.py migrate

# 3. Collect static files
/home/chris/.pyenv/versions/iolabs/bin/python manage.py collectstatic --noinput

# 4. Restart the service
systemctl --user restart django-iolabs
```

## Service Management

```bash
# Check status
systemctl --user status django-iolabs

# Restart
systemctl --user restart django-iolabs

# View logs (follow)
journalctl --user -u django-iolabs -f

# View recent logs
journalctl --user -u django-iolabs --since "10 minutes ago"
```

## Verification Endpoints

After deploying, verify these endpoints:

| Endpoint                                | Expected                   |
| --------------------------------------- | -------------------------- |
| `/agent-builder/`                       | SPA loads (200)            |
| `/agent-builder/api/agents/`            | Auth required (401)        |
| `/agent-builder/api/schema/swagger-ui/` | Swagger UI loads (200)     |
| `/django-admin/agent_builder/`          | Admin login redirect (302) |

## Running Tests

```bash
cd /storage/Projects/webapps/IOLabs/AI/django-agent_builder
/home/chris/.pyenv/versions/iolabs/bin/python -m pytest tests/ -v
```

## Related Docs

- [IOLabs README](/storage/Projects/webapps/IOLabs/iolabs/iolabs/README.md)
- [Creating and Deploying Reusable Apps](/storage/Projects/webapps/IOLabs/iolabs/iolabs/docs/creating-and-deploying-reusable-apps.md)
