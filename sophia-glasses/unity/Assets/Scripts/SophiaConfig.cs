using UnityEngine;

/// <summary>
/// Runtime configuration for the sophia-glasses Unity app.
/// One ScriptableObject asset (typically Assets/Settings/SophiaConfig.asset)
/// holds all server URLs, room semantics, and identity defaults.
///
/// Per AGENTS.md: this single ScriptableObject is the ONE place to edit
/// runtime config -- no recompile needed.
///
/// To create: in the Project panel, right-click Assets/Settings folder,
/// then Create > Sophia > Config.
/// </summary>
[CreateAssetMenu(fileName = "SophiaConfig", menuName = "Sophia/Config", order = 0)]
public class SophiaConfig : ScriptableObject
{
    [Header("LiveKit Server")]
    [Tooltip("Full WebSocket URL of the livekit-server. " +
             "For local dev with Tailscale: ws://<mac-tailscale-ip>:7880")]
    public string liveKitUrl = "ws://100.69.34.194:7880";

    [Tooltip("Full URL of the sophia-agent token-mint endpoint. " +
             "For local dev with Tailscale: http://<mac-tailscale-ip>:8001/token")]
    public string tokenEndpoint = "http://100.69.34.194:8001/token";

    [Tooltip("Optional shared API key for the token-mint endpoint. " +
             "When set, the X-API-Key header is sent on every /token POST. " +
             "Must match SOPHIA_TOKEN_API_KEY in sophia-agent/.env.production. " +
             "Leave EMPTY to skip auth (dev / MVP demo). Same opt-in pattern " +
             "as the server side: empty here = no header sent, non-empty = " +
             "header included on every request.")]
    public string tokenApiKey = "";

    [Header("Room & Agent")]
    [Tooltip("Agent name as registered in sophia-agent/src/agent.py " +
             "(@server.rtc_session(agent_name=...)). Token-mint includes " +
             "this in the JWT's RoomConfig.agents so the worker is " +
             "auto-dispatched into the room.")]
    public string agentName = "sophia-agent";

    [Tooltip("Room name. LEAVE EMPTY for unique-per-launch (Scenario B = " +
             "isolated per-user Sophia sessions). Set to a fixed value " +
             "(e.g. 'maintenance-bay-3') for Scenario A = shared room " +
             "across multiple clients (browser + glasses, or two pairs " +
             "of glasses, etc.).")]
    public string roomName = "";

    [Header("Participant Identity")]
    [Tooltip("Identity for this Unity participant. LEAVE EMPTY to " +
             "auto-generate a unique one at launch. Use a fixed value " +
             "(e.g. 'tech-anna') for repeatable sessions.")]
    public string participantIdentity = "";

    [Tooltip("Display name shown to other room participants. Defaults to " +
             "'Sophia Glasses User' if empty.")]
    public string participantName = "";

    [Header("Audio")]
    [Tooltip("Microphone device index. -1 = use default. Set to a " +
             "specific index if Beam Pro picks the wrong device.")]
    public int microphoneDeviceIndex = -1;
}
