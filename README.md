agent_builder
=============

agent_builder description

Quick start
-----------

1. `pip install` the app
    - Local: `pip install -e /path/to/django-agent_builder/repo`

2. Add "agent_builder" to your INSTALLED_APPS setting like this::

    INSTALLED_APPS = [
        ...
        'agent_builder',
    ]

3. Include the agent_builder URLconf in your project urls.py like this::

    path('agent_builder/', include('agent_builder.urls')),

4. Run `python manage.py migrate` to create the agent_builder models.
