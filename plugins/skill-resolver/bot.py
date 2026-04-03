#!/usr/bin/env python3
"""
Skill Resolver Bot — Matrix bot that discovers agent skills from kubeclaw pods
and publishes them to Matrix rooms as state events.

Commands:
  /skills <agentId>   — Fetch and publish skills for the named agent
  /skills             — Auto-detect agent from room members and publish skills
  /skills list        — List all discovered agents

Environment:
  MATRIX_HOMESERVER   — Matrix homeserver URL (e.g., https://matrix.zacx.dev)
  MATRIX_ACCESS_TOKEN — Bot's access token
  MATRIX_BOT_USER_ID  — Bot's Matrix user ID (e.g., @skill-resolver:matrix.homelab.lan)
  KUBE_NAMESPACE_PREFIX — Namespace prefix for agent pods (default: devpod-)
  KUBE_SERVICE_SUFFIX   — Service name suffix (default: -devpod)
  SKILLS_API_PORT       — Port for skills API on agent pods (default: 18790)
  AGENT_HOMESERVER      — Matrix homeserver suffix for agent bot users (default: matrix.homelab.lan)
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

# Config from environment
HOMESERVER = os.environ.get("MATRIX_HOMESERVER", "").rstrip("/")
ACCESS_TOKEN = os.environ.get("MATRIX_ACCESS_TOKEN", "")
BOT_USER_ID = os.environ.get("MATRIX_BOT_USER_ID", "")
NS_PREFIX = os.environ.get("KUBE_NAMESPACE_PREFIX", "devpod-")
SVC_SUFFIX = os.environ.get("KUBE_SERVICE_SUFFIX", "-devpod")
SKILLS_PORT = int(os.environ.get("SKILLS_API_PORT", "18790"))
AGENT_HS = os.environ.get("AGENT_HOMESERVER", "matrix.homelab.lan")

SYNC_TIMEOUT = 30000  # 30s long-poll
SKILLS_STATE_TYPE = "dev.clankselect.agent_skills"


def matrix_request(method, path, body=None):
    """Make an authenticated Matrix API request."""
    url = f"{HOMESERVER}/_matrix/client/v3{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        print(f"[ERROR] {method} {path} -> {e.code}: {err_body}", file=sys.stderr)
        return None


def send_notice(room_id, text):
    """Send an m.notice message to a room."""
    txn = f"sr-{int(time.time() * 1000)}"
    encoded = urllib.parse.quote(room_id, safe="")
    matrix_request("PUT", f"/rooms/{encoded}/send/m.room.message/{txn}", {
        "msgtype": "m.notice",
        "body": text,
    })


def set_skills_state(room_id, skills):
    """Set dev.clankselect.agent_skills state event in a room."""
    encoded = urllib.parse.quote(room_id, safe="")
    result = matrix_request("PUT",
        f"/rooms/{encoded}/state/{SKILLS_STATE_TYPE}/",
        {"skills": skills})
    return result is not None


def discover_agents_k8s():
    """Discover agent pods via K8s API (in-cluster)."""
    agents = []
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

    if not os.path.exists(token_path):
        print("[WARN] Not running in K8s cluster, skipping service discovery", file=sys.stderr)
        return agents

    with open(token_path) as f:
        k8s_token = f.read().strip()

    # List all namespaces matching the devpod prefix
    import ssl
    ctx = ssl.create_default_context(cafile=ca_path)

    try:
        req = urllib.request.Request(
            "https://kubernetes.default.svc/api/v1/namespaces",
            headers={"Authorization": f"Bearer {k8s_token}"}
        )
        with urllib.request.urlopen(req, context=ctx) as resp:
            ns_data = json.loads(resp.read())

        for ns in ns_data.get("items", []):
            ns_name = ns["metadata"]["name"]
            if not ns_name.startswith(NS_PREFIX):
                continue
            agent_id = ns_name[len(NS_PREFIX):]
            svc_name = f"{agent_id}{SVC_SUFFIX}"
            agents.append({
                "id": agent_id,
                "namespace": ns_name,
                "service": svc_name,
                "skillsUrl": f"http://{svc_name}.{ns_name}.svc.cluster.local:{SKILLS_PORT}/api/skills",
                "botUserId": f"@{agent_id}:{AGENT_HS}",
            })
    except Exception as e:
        print(f"[ERROR] K8s discovery failed: {e}", file=sys.stderr)

    return agents


def fetch_skills(skills_url):
    """Fetch skills from an agent pod's skills API."""
    try:
        req = urllib.request.Request(skills_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[WARN] Failed to fetch skills from {skills_url}: {e}", file=sys.stderr)
        return None


def get_room_members(room_id):
    """Get joined members of a room."""
    encoded = urllib.parse.quote(room_id, safe="")
    result = matrix_request("GET", f"/rooms/{encoded}/joined_members")
    if result and "joined" in result:
        return list(result["joined"].keys())
    return []


def handle_command(room_id, command_text):
    """Handle a /skills command."""
    agents = discover_agents_k8s()
    parts = command_text.strip().split()

    # /skills list — show all agents
    if len(parts) >= 2 and parts[1] == "list":
        if not agents:
            send_notice(room_id, "No agent pods discovered.")
            return
        lines = [f"Discovered {len(agents)} agent(s):"]
        for a in agents:
            skills = fetch_skills(a["skillsUrl"])
            count = len(skills) if skills else "?"
            lines.append(f"  {a['id']} — {count} skills ({a['botUserId']})")
        send_notice(room_id, "\n".join(lines))
        return

    # /skills <agentId> — publish skills for specific agent
    if len(parts) >= 2:
        agent_id = parts[1]
        agent = next((a for a in agents if a["id"] == agent_id), None)
        if not agent:
            # Try fuzzy match
            agent = next((a for a in agents if agent_id in a["id"]), None)
        if not agent:
            send_notice(room_id, f"Agent '{agent_id}' not found. Use `/skills list` to see available agents.")
            return
        publish_for_agent(room_id, agent)
        return

    # /skills — auto-detect from room members
    members = get_room_members(room_id)
    matched = []
    for a in agents:
        if a["botUserId"] in members:
            matched.append(a)

    if not matched:
        send_notice(room_id, "No agent bots detected in this room. Use `/skills <agentId>` to specify one.")
        return

    for agent in matched:
        publish_for_agent(room_id, agent)


def publish_for_agent(room_id, agent):
    """Fetch and publish skills for a specific agent."""
    skills = fetch_skills(agent["skillsUrl"])
    if not skills:
        send_notice(room_id, f"Could not fetch skills for {agent['id']}.")
        return

    if set_skills_state(room_id, skills):
        skill_names = ", ".join(s.get("trigger", s.get("id", "?")) for s in skills)
        send_notice(room_id, f"{agent['id']}: {skill_names}")
    else:
        send_notice(room_id, f"Failed to publish skills for {agent['id']} (permission denied?).")


def sync_loop():
    """Main Matrix /sync loop."""
    print(f"[INFO] Skill Resolver Bot starting as {BOT_USER_ID}")
    print(f"[INFO] Homeserver: {HOMESERVER}")

    since = None

    while True:
        try:
            params = urllib.parse.urlencode({
                "timeout": str(SYNC_TIMEOUT),
                **({"since": since} if since else {}),
                "filter": json.dumps({
                    "room": {
                        "timeline": {"types": ["m.room.message"], "limit": 10},
                        "state": {"types": []},
                        "ephemeral": {"types": []},
                    },
                    "presence": {"types": []},
                }),
            })

            req = urllib.request.Request(
                f"{HOMESERVER}/_matrix/client/v3/sync?{params}",
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            )
            with urllib.request.urlopen(req, timeout=SYNC_TIMEOUT // 1000 + 10) as resp:
                data = json.loads(resp.read())

            since = data.get("next_batch")

            # Process joined room events
            for room_id, room_data in data.get("rooms", {}).get("join", {}).items():
                for event in room_data.get("timeline", {}).get("events", []):
                    if event.get("type") != "m.room.message":
                        continue
                    if event.get("sender") == BOT_USER_ID:
                        continue

                    body = event.get("content", {}).get("body", "")
                    if body.startswith("/skills"):
                        print(f"[CMD] {room_id}: {body}")
                        handle_command(room_id, body)

            # Auto-join invited rooms
            for room_id in data.get("rooms", {}).get("invite", {}):
                print(f"[JOIN] Accepting invite to {room_id}")
                encoded = urllib.parse.quote(room_id, safe="")
                matrix_request("POST", f"/rooms/{encoded}/join", {})

        except urllib.error.URLError as e:
            print(f"[ERROR] Sync failed: {e}", file=sys.stderr)
            time.sleep(5)
        except Exception as e:
            print(f"[ERROR] Unexpected: {e}", file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    if not HOMESERVER or not ACCESS_TOKEN or not BOT_USER_ID:
        print("ERROR: MATRIX_HOMESERVER, MATRIX_ACCESS_TOKEN, and MATRIX_BOT_USER_ID must be set", file=sys.stderr)
        sys.exit(1)
    sync_loop()
