"""Tests for simulate mode context assembly."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from agent_builder.models import Agent
from agent_builder.simulate import SimulateSessionError, simulate_session

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="testuser", password="pass")


@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def agent(user):
    return Agent.objects.create(
        name="test-agent",
        display_name="Test Agent",
        source="coderoo",
        model="sonnet",
        user=user,
    )


@pytest.fixture
def preview_payload():
    return {
        "status": "success",
        "project_path": "/tmp/project",
        "role_description": "Role markdown",
        "global_instructions": "Global instructions",
        "docs": [{"/tmp/project/AGENTS.md": "Project config file"}],
        "task_docs": [{"description.md": "Task description"}],
        "available_instructions": [["my-instruction", "Instruction description"]],
        "available_commands": {"send_sms": "Send an SMS"},
        "active_tasks": ["simulate-use-preview-context"],
        "relevant_files": ["agent_builder/simulate.py"],
        "md_files": [{"/tmp/project/AGENTS.md": "Agent file content"}],
    }


@pytest.mark.django_db
class TestSimulateSession:
    @patch("agent_builder.simulate.subprocess.run")
    def test_simulate_session_uses_preview_context_command(self, mock_run, agent, preview_payload):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(preview_payload),
            stderr="",
        )

        result = simulate_session(
            agent,
            project_path="/tmp/project",
            role="orchestrator",
            context="my-context",
            task="my-task",
            runtime="codex",
        )

        assert result == preview_payload

        command = mock_run.call_args.args[0]
        assert command[0].endswith("coderoo")
        assert command[1:3] == ["preview-context", "--json"]
        assert "--agent" in command and "test-agent" in command
        assert "--role" in command and "orchestrator" in command
        assert "--context" in command and "my-context" in command
        assert "--task" in command and "my-task" in command
        assert "--runtime" in command and "codex" in command
        assert "--include-md-files" in command
        assert "--path" in command and "/tmp/project" in command

    @patch("agent_builder.simulate.subprocess.run")
    def test_simulate_session_moves_md_files_to_first_key(self, mock_run, agent, preview_payload):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(preview_payload),
            stderr="",
        )

        result = simulate_session(agent)

        assert list(result.keys())[0] == "md_files"

    @patch("agent_builder.simulate.subprocess.run")
    def test_simulate_session_propagates_project_path(self, mock_run, agent, preview_payload):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(preview_payload),
            stderr="",
        )

        simulate_session(agent, project_path="/tmp/project")

        command = mock_run.call_args.args[0]
        assert "--path" in command
        assert "/tmp/project" in command

    @patch("agent_builder.simulate.subprocess.run")
    def test_simulate_session_command_failure_raises(self, mock_run, agent):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="preview failed",
        )

        with pytest.raises(SimulateSessionError, match="preview failed"):
            simulate_session(agent)

    @patch("agent_builder.simulate.subprocess.run")
    def test_simulate_session_invalid_json_raises(self, mock_run, agent):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="{bad json}",
            stderr="",
        )

        with pytest.raises(SimulateSessionError, match="invalid JSON"):
            simulate_session(agent)

    @patch("agent_builder.simulate.subprocess.run")
    def test_simulate_session_executable_disappears_raises(self, mock_run, agent):
        mock_run.side_effect = FileNotFoundError("coderoo not found")

        with pytest.raises(SimulateSessionError, match="became unavailable"):
            simulate_session(agent)

    @patch("agent_builder.simulate.os.access", return_value=False)
    @patch("agent_builder.simulate.Path.exists", return_value=False)
    @patch("agent_builder.simulate.shutil.which", return_value=None)
    def test_simulate_session_missing_command_raises(
        self, _mock_which, _mock_exists, _mock_access, agent
    ):
        with pytest.raises(SimulateSessionError, match="command not found"):
            simulate_session(agent)


@pytest.mark.django_db
class TestSimulateAPI:
    def test_simulate_endpoint_requires_auth(self, client):
        resp = client.post(
            "/agent-builder/api/simulate/",
            {"agent_id": 1},
            content_type="application/json",
        )
        assert resp.status_code in (401, 403)

    def test_simulate_endpoint_requires_agent_id(self, api_client):
        client, _ = api_client
        resp = client.post(
            "/agent-builder/api/simulate/",
            {},
            format="json",
        )
        assert resp.status_code == 400

    @patch("agent_builder.simulate.simulate_session")
    def test_simulate_endpoint_returns_context(self, mock_simulate, api_client, agent):
        client, _ = api_client
        mock_simulate.return_value = {"status": "success", "project_path": "/tmp/project"}

        resp = client.post(
            "/agent-builder/api/simulate/",
            {"agent_id": agent.pk, "project_path": "/tmp/project"},
            format="json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["project_path"] == "/tmp/project"

        call_args = mock_simulate.call_args
        assert call_args.args[0] == agent
        assert call_args.args[1] == "/tmp/project"

    @patch("agent_builder.simulate.simulate_session")
    def test_simulate_endpoint_passes_preview_flags(self, mock_simulate, api_client, agent):
        client, _ = api_client
        mock_simulate.return_value = {"status": "success"}

        resp = client.post(
            "/agent-builder/api/simulate/",
            {
                "agent_id": agent.pk,
                "role": "orchestrator",
                "context": "project-researcher",
                "task": "my-task",
                "runtime": "codex",
            },
            format="json",
        )

        assert resp.status_code == 200
        call_kwargs = mock_simulate.call_args.kwargs
        assert call_kwargs["role"] == "orchestrator"
        assert call_kwargs["context"] == "project-researcher"
        assert call_kwargs["task"] == "my-task"
        assert call_kwargs["runtime"] == "codex"

    @patch("agent_builder.simulate.simulate_session")
    def test_simulate_endpoint_returns_502_on_preview_failure(
        self, mock_simulate, api_client, agent
    ):
        client, _ = api_client
        mock_simulate.side_effect = SimulateSessionError("preview failed")

        resp = client.post(
            "/agent-builder/api/simulate/",
            {"agent_id": agent.pk},
            format="json",
        )

        assert resp.status_code == 502
        assert resp.json()["detail"] == "preview failed"

    def test_simulate_endpoint_agent_not_found(self, api_client):
        client, _ = api_client
        resp = client.post(
            "/agent-builder/api/simulate/",
            {"agent_id": 99999},
            format="json",
        )
        assert resp.status_code == 404

    def test_simulate_endpoint_other_users_agent(self, api_client):
        client, _ = api_client
        other_user = User.objects.create_user(username="other", password="pass")
        other_agent = Agent.objects.create(
            name="other-agent",
            display_name="Other Agent",
            source="claude",
            model="sonnet",
            user=other_user,
        )
        resp = client.post(
            "/agent-builder/api/simulate/",
            {"agent_id": other_agent.pk},
            format="json",
        )
        assert resp.status_code == 404
